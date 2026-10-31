package pt.iptvplayer.tv.pairing

import android.content.Context
import android.net.ConnectivityManager
import java.net.Inet4Address
import java.net.InetAddress
import java.net.NetworkInterface

class NetworkAddressResolver(context: Context) {
    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    fun currentIpv4Address(): InetAddress? {
        // 1. Try active network
        val activeAddress = connectivityManager.activeNetwork?.let { network ->
            findIpv4InLinkProperties(network)
        }
        if (activeAddress != null) return activeAddress

        // 2. Try all networks known to ConnectivityManager
        for (network in connectivityManager.allNetworks) {
            val address = findIpv4InLinkProperties(network)
            if (address != null) return address
        }

        // 3. Fallback: query physical NetworkInterfaces directly (handles Ethernet eth0, CGNAT, etc.)
        return runCatching {
            val interfaces = NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
            // Prefer Ethernet and Wi-Fi interfaces over virtual/tunnel interfaces
            val sorted = interfaces.sortedByDescending { iface ->
                val name = iface.name.lowercase()
                when {
                    name.startsWith("eth") -> 3
                    name.startsWith("wlan") -> 2
                    name.startsWith("en") -> 2
                    !iface.isVirtual && !iface.isLoopback -> 1
                    else -> 0
                }
            }
            sorted.asSequence()
                .filter { it.isUp && !it.isLoopback }
                .flatMap { it.inetAddresses.asSequence() }
                .filterIsInstance<Inet4Address>()
                .firstOrNull { isUsableLanAddress(it) }
        }.getOrNull()
    }

    private fun findIpv4InLinkProperties(network: android.net.Network): Inet4Address? {
        val linkProps = connectivityManager.getLinkProperties(network) ?: return null
        val candidates = linkProps.linkAddresses
            .asSequence()
            .map { it.address }
            .filterIsInstance<Inet4Address>()
            .filter { isUsableLanAddress(it) }
            .toList()

        return candidates.firstOrNull { it.isSiteLocalAddress } ?: candidates.firstOrNull()
    }

    private fun isUsableLanAddress(address: Inet4Address): Boolean {
        if (address.isLoopbackAddress || address.isAnyLocalAddress || address.isLinkLocalAddress) {
            return false
        }
        // Accept site local (10.x, 172.16-31.x, 192.168.x) or CGNAT (100.64.0.0/10) or any non-loopback
        return true
    }
}
