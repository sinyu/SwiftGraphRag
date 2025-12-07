import duckdb
import os
from pathlib import Path

class DuckDBStore:
    def __init__(self, db_path="rag_data.duckdb"):
        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self._init_extensions()
        self._init_schema()

    def _init_extensions(self):
        # Install and load vector extension (vss)
        try:
            self.conn.execute("INSTALL vss; LOAD vss;")
            print("DuckDB vss extension loaded successfully")
        except Exception as e:
            print(f"Warning: Failed to load DuckDB vss extension: {e}")
            print("Vector search will not work, but basic graph ops might.")
        
        # Try to install/load duckpgq for graph operations
        self.use_pgq = False
        try:
            # Try from community repository first
            self.conn.execute("INSTALL duckpgq FROM community;")
            self.conn.execute("LOAD duckpgq;")
            self.use_pgq = True
            print("DuckPGQ extension loaded successfully")
        except Exception as e1:
            # Try from core repository
            try:
                self.conn.execute("INSTALL duckpgq;")
                self.conn.execute("LOAD duckpgq;")
                self.use_pgq = True
                print("DuckPGQ extension loaded successfully")
            except Exception as e2:
                print(f"DuckPGQ not available ({e1}, {e2}). Using SQL tables for graph.")


    def _init_schema(self):
        # Vector table for chunks
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id VARCHAR,
                space_id VARCHAR,
                content TEXT,
                embedding FLOAT[384], -- Assuming 384 dim for mini-model
                metadata JSON
            )
        """)
        
        # Graph tables
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id VARCHAR PRIMARY KEY,
                label VARCHAR,
                properties JSON
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                source VARCHAR,
                target VARCHAR,
                label VARCHAR,
                properties JSON,
                FOREIGN KEY (source) REFERENCES nodes(id),
                FOREIGN KEY (target) REFERENCES nodes(id)
            )
        """)

    def add_chunks(self, chunks, space_id):
        """
        Add document chunks with embeddings.
        chunks: list of (id, content, embedding, metadata)
        """
        # Use appender for bulk insert
        for chunk in chunks:
            cid, content, emb, meta = chunk
            # Convert meta to json string
            import json
            meta_json = json.dumps(meta)
            self.conn.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?)", 
                              (cid, space_id, content, emb, meta_json))

    def search_vectors(self, query_embedding, space_id, k=5, text_query=None, target_doc=None):
        """
        Vector search using DuckDB vector similarity with optional document filter.
        """
        try:
            # Use a threshold to filter out poor matches (e.g., < 0.3)
            # Adjust threshold based on embedding model characteristics
            threshold = 0.3
            
            if target_doc and target_doc != "all":
                return self.conn.execute("""
                    SELECT content, metadata, array_cosine_similarity(embedding, ?::FLOAT[384]) as score
                    FROM chunks
                    WHERE space_id = ? 
                    AND json_extract_string(metadata, '$.source') = ?
                    AND array_cosine_similarity(embedding, ?::FLOAT[384]) > ?
                    ORDER BY score DESC
                    LIMIT ?
                """, (query_embedding, space_id, target_doc, query_embedding, threshold, k)).fetchall()
            else:
                return self.conn.execute("""
                    SELECT content, metadata, array_cosine_similarity(embedding, ?::FLOAT[384]) as score
                    FROM chunks
                    WHERE space_id = ?
                    AND array_cosine_similarity(embedding, ?::FLOAT[384]) > ?
                    ORDER BY score DESC
                    LIMIT ?
                """, (query_embedding, space_id, query_embedding, threshold, k)).fetchall()
        except Exception as e:
            print(f"Vector search failed ({e}). Falling back to keyword search.")
            if text_query:
                # Simple keyword search fallback
                clean_query = text_query.replace("'", "").replace("%", "")
                if target_doc and target_doc != "all":
                    return self.conn.execute(f"""
                        SELECT content, metadata, 0.5 as score
                        FROM chunks
                        WHERE space_id = ? 
                        AND json_extract_string(metadata, '$.source') = ?
                        AND content ILIKE '%{clean_query}%'
                        LIMIT ?
                    """, (space_id, target_doc, k)).fetchall()
                else:
                    return self.conn.execute(f"""
                        SELECT content, metadata, 0.5 as score
                        FROM chunks
                        WHERE space_id = ? AND content ILIKE '%{clean_query}%'
                        LIMIT ?
                    """, (space_id, k)).fetchall()
            return []

    def add_node(self, node_id, label, props={}):
        import json
        self.conn.execute("INSERT OR IGNORE INTO nodes VALUES (?, ?, ?)", 
                          (node_id, label, json.dumps(props)))

    def add_edge(self, source, target, label, props={}):
        import json
        self.conn.execute("INSERT INTO edges VALUES (?, ?, ?, ?)", 
                          (source, target, label, json.dumps(props)))

    def get_graph_context(self, node_ids):
        """
        Retrieve 1-hop neighborhood for given nodes.
        """
        if not node_ids:
            return []
        
        placeholders = ','.join(['?'] * len(node_ids))
        query = f"""
            SELECT source, target, label 
            FROM edges 
            WHERE source IN ({placeholders}) OR target IN ({placeholders})
        """
        # Duplicate node_ids for both IN clauses
        return self.conn.execute(query, node_ids + node_ids).fetchall()

    def delete_document(self, space_id, document_title):
        """
        Delete all chunks and graph nodes/edges associated with a document.
        """
        import json
        
        # 1. Get all chunk IDs for this document
        chunks = self.conn.execute("""
            SELECT id, metadata FROM chunks 
            WHERE space_id = ? AND json_extract_string(metadata, '$.source') = ?
        """, (space_id, document_title)).fetchall()
        
        chunk_ids = [c[0] for c in chunks]
        
        # 2. Delete chunks
        self.conn.execute("""
            DELETE FROM chunks 
            WHERE space_id = ? AND json_extract_string(metadata, '$.source') = ?
        """, (space_id, document_title))
        
        # 3. Delete nodes created from these chunks
        if chunk_ids:
            placeholders = ','.join(['?'] * len(chunk_ids))
            # 4. Delete edges related to deleted nodes (cascade)
            self.conn.execute(f"""
                DELETE FROM edges 
                WHERE json_extract_string(properties, '$.source_chunk') IN ({placeholders})
            """, chunk_ids)

            # 5. Delete nodes ONLY if they are orphaned (not used in any edges)
            # We check if the node ID exists in either source or target of ANY remaining edge
            self.conn.execute(f"""
                DELETE FROM nodes 
                WHERE json_extract_string(properties, '$.source_chunk') IN ({placeholders})
                AND id NOT IN (SELECT source FROM edges)
                AND id NOT IN (SELECT target FROM edges)
            """, chunk_ids)
        
        print(f"Deleted {len(chunks)} chunks and associated graph data for '{document_title}'")
        return len(chunks)

    def delete_space(self, space_id):
        """
        Delete all data associated with a space.
        """
        # 1. Get all chunk IDs for this space
        chunks = self.conn.execute("SELECT id FROM chunks WHERE space_id = ?", (space_id,)).fetchall()
        chunk_ids = [c[0] for c in chunks]
        
        if not chunk_ids:
            return 0
            
        # 2. Delete nodes and edges derived from these chunks
        # We process in batches to avoid query length limits if many chunks
        batch_size = 1000
        for i in range(0, len(chunk_ids), batch_size):
            batch = chunk_ids[i:i+batch_size]
            placeholders = ','.join(['?'] * len(batch))
            
            # Delete edges first (FK constraint usually, though DuckDB is loose here, logical order is better)
            self.conn.execute(f"""
                DELETE FROM edges 
                WHERE json_extract_string(properties, '$.source_chunk') IN ({placeholders})
            """, batch)
            
            # Delete nodes ONLY if orphaned
            self.conn.execute(f"""
                DELETE FROM nodes 
                WHERE json_extract_string(properties, '$.source_chunk') IN ({placeholders})
                AND id NOT IN (SELECT source FROM edges)
                AND id NOT IN (SELECT target FROM edges)
            """, batch)

        # 3. Delete chunks
        self.conn.execute("DELETE FROM chunks WHERE space_id = ?", (space_id,))
        
        print(f"Deleted space {space_id}: {len(chunks)} chunks and associated graph data.")
        return len(chunks)
