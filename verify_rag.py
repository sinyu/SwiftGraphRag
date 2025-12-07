import duckdb
import json

def verify():
    print("Connecting to DuckDB...")
    try:
        conn = duckdb.connect("rag_data.duckdb")
    except Exception as e:
        print(f"Failed to connect: {e}")
        return

    # 1. Check Tables
    tables = ["chunks", "nodes", "edges"]
    for t in tables:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"Table '{t}' has {count} rows.")
            
            if count > 0:
                print(f"Sample from '{t}':")
                print(conn.execute(f"SELECT * FROM {t} LIMIT 1").fetchall())
        except Exception as e:
            print(f"Error checking table '{t}': {e}")

    # 2. Test Vector Search (Expect Failure)
    print("\nTesting Vector Search...")
    try:
        query_vec = [0.1] * 384
        # Mock space_id - just check if function exists
        conn.execute("""
            SELECT content, array_cosine_similarity(embedding, ?::FLOAT[384]) as score
            FROM chunks
            LIMIT 1
        """, (query_vec,))
        print("Vector search query executed successfully (Unexpected if extension missing).")
    except Exception as e:
        print(f"Vector search failed as expected: {e}")

if __name__ == "__main__":
    verify()
