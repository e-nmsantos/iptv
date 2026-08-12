"""Paginated channel reads isolated from the database facade."""


class CatalogRepository:
    def __init__(self, connections, row_mapper, stream_types):
        self._connections = connections
        self._row_mapper = row_mapper
        self._stream_types = stream_types

    def page(
        self,
        playlist_id: int,
        content_type: str,
        page: int = 0,
        page_size: int = 250,
        group: str = "",
        query: str = "",
    ):
        if page < 0 or page_size < 1 or page_size > 1000:
            raise ValueError("Página ou tamanho de página inválido.")
        stream_types = self._stream_types(content_type)
        placeholders = ",".join("?" for _ in stream_types)
        clauses = ["playlist_id = ?", f"stream_type IN ({placeholders})"]
        params = [playlist_id, *stream_types]
        if group:
            clauses.append("group_name = ?")
            params.append(group)
        if query.strip():
            clauses.append("instr(lower(name), lower(?)) > 0")
            params.append(query.strip())
        params.extend((page_size, page * page_size))
        with self._connections() as conn:
            rows = conn.execute(
                f"""SELECT * FROM channels WHERE {' AND '.join(clauses)}
                    ORDER BY group_name COLLATE NOCASE, name COLLATE NOCASE, id
                    LIMIT ? OFFSET ?""",
                params,
            ).fetchall()
        return [self._row_mapper(row) for row in rows]

    def count(
        self,
        playlist_id: int,
        content_type: str,
        group: str = "",
        query: str = "",
    ) -> int:
        stream_types = self._stream_types(content_type)
        placeholders = ",".join("?" for _ in stream_types)
        clauses = ["playlist_id = ?", f"stream_type IN ({placeholders})"]
        params = [playlist_id, *stream_types]
        if group:
            clauses.append("group_name = ?")
            params.append(group)
        if query.strip():
            clauses.append("instr(lower(name), lower(?)) > 0")
            params.append(query.strip())
        with self._connections() as conn:
            return int(
                conn.execute(
                    f"SELECT COUNT(*) FROM channels WHERE {' AND '.join(clauses)}",
                    params,
                ).fetchone()[0]
            )
