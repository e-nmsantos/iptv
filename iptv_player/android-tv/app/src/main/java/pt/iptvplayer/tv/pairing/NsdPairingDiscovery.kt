package pt.iptvplayer.tv.pairing

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log

class NsdPairingDiscovery(context: Context) {
    private val nsdManager = context.getSystemService(Context.NSD_SERVICE) as? NsdManager
    private var registrationListener: NsdManager.RegistrationListener? = null

    fun registerService(port: Int, serviceName: String = "IPTV Player TV") {
        if (nsdManager == null) return
        unregisterService()

        val serviceInfo = NsdServiceInfo().apply {
            this.serviceName = serviceName
            this.serviceType = "_iptv-pair._tcp"
            this.port = port
        }

        val listener = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(serviceInfo: NsdServiceInfo) {
                Log.d(TAG, "NSD Service registered: ${serviceInfo.serviceName} on port ${serviceInfo.port}")
            }

            override fun onRegistrationFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                Log.w(TAG, "NSD Registration failed: $errorCode")
            }

            override fun onServiceUnregistered(serviceInfo: NsdServiceInfo) {
                Log.d(TAG, "NSD Service unregistered: ${serviceInfo.serviceName}")
            }

            override fun onUnregistrationFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                Log.w(TAG, "NSD Unregistration failed: $errorCode")
            }
        }

        registrationListener = listener
        runCatching {
            nsdManager?.registerService(serviceInfo, NsdManager.PROTOCOL_DNS_SD, listener)
        }.onFailure { error ->
            Log.w(TAG, "Could not register NSD service", error)
        }
    }

    fun unregisterService() {
        val listener = registrationListener ?: return
        registrationListener = null
        runCatching {
            nsdManager?.unregisterService(listener)
        }.onFailure { error ->
            Log.w(TAG, "Could not unregister NSD service", error)
        }
    }

    companion object {
        private const val TAG = "NsdPairingDiscovery"
    }
}

