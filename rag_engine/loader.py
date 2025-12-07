from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from .store import DuckDBStore
import os

class DocumentIngestor:
    def __init__(self, store: DuckDBStore):
        self.store = store
        # Initialize local embeddings using HuggingFace
        # Model will be cached locally in ~/.cache/huggingface/hub
        from django.conf import settings
        config = settings.GRAPHRAG_CONFIG
        
        model_name = config["EMBEDDING_MODEL_NAME"]
        cache_folder = config["EMBEDDING_CACHE_FOLDER"]
        
        self.embeddings = HuggingFaceEmbeddings(
            model_name=model_name,
            cache_folder=cache_folder,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
        print(f"Loaded local embedding model: {model_name}")
 

    def ingest(self, file_path, space_id, source_name=None):
        """
        Load, chunk, embed, and store document.
        """
        # 1. Load
        if file_path.endswith('.pdf'):
            loader = PyPDFLoader(file_path)
            docs = loader.load()
        else:
            # Try default (UTF-8)
            try:
                loader = TextLoader(file_path, encoding='utf-8')
                docs = loader.load()
            except Exception:
                # Try autodetect if chardet is available
                try:
                    loader = TextLoader(file_path, autodetect_encoding=True)
                    docs = loader.load()
                except Exception:
                    # Fallback to latin-1 which reads everything as bytes-mapped-to-chars
                    print(f"Warning: Could not detect encoding for {file_path}, falling back to latin-1")
                    loader = TextLoader(file_path, encoding='latin-1')
                    docs = loader.load()
        
        # Get chunking config
        from django.conf import settings
        config = settings.GRAPHRAG_CONFIG
        chunk_size = config.get("CHUNK_SIZE", 500)
        chunk_overlap = config.get("CHUNK_OVERLAP", 50)
        
        # 2. Split
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = splitter.split_documents(docs)
        
        # 3. Embed & Store (Mocking embedding for now if model not present)
        data_to_insert = []
        final_source = source_name if source_name else os.path.basename(file_path)
        
        for i, chunk in enumerate(chunks):
            cid = f"{space_id}_{final_source}_{i}"
            embedding = self._get_embedding(chunk.page_content)
            metadata = chunk.metadata
            metadata['source'] = final_source
            data_to_insert.append((cid, chunk.page_content, embedding, metadata))
            
            # 4. Simple Graph Extraction (Entity -> Entity)
            # Placeholder: Extract capitalized words as nodes
            self._extract_graph(chunk.page_content, cid)

        self.store.add_chunks(data_to_insert, space_id)
        
        # Return full text for summarization
        return "\n".join([d.page_content for d in docs])

    def _get_embedding(self, text):
        return self.embeddings.embed_query(text)


    def _extract_graph(self, text, chunk_id):
        # Very simple heuristic extraction for demo
        words = text.split()
        entities = [w.strip(".,") for w in words if w[0].isupper() and len(w) > 3]
        
        for entity in set(entities):
            # Add node
            self.store.add_node(entity, "Entity", {"source_chunk": chunk_id})
            
        # Connect adjacent entities
        for i in range(len(entities) - 1):
            self.store.add_edge(entities[i], entities[i+1], "RELATED", {"source_chunk": chunk_id})

    def ingest_url(self, url, space_id):
        """
        Load content from URL, chunk, embed, and store.
        """
        from langchain_community.document_loaders import WebBaseLoader
        
        # 1. Load
        loader = WebBaseLoader(url)
        docs = loader.load()
        
        # Get chunking config
        from django.conf import settings
        config = settings.GRAPHRAG_CONFIG
        chunk_size = config.get("CHUNK_SIZE", 500)
        chunk_overlap = config.get("CHUNK_OVERLAP", 50)
        
        # 2. Split
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = splitter.split_documents(docs)
        
        # 3. Embed & Store
        data_to_insert = []
        for i, chunk in enumerate(chunks):
            cid = f"{space_id}_url_{i}"
            embedding = self._get_embedding(chunk.page_content)
            metadata = chunk.metadata
            metadata['source'] = url
            data_to_insert.append((cid, chunk.page_content, embedding, metadata))
            
            # 4. Graph Extraction
            self._extract_graph(chunk.page_content, cid)

        self.store.add_chunks(data_to_insert, space_id)
        
        # Return full text
        return "\n".join([d.page_content for d in docs])
