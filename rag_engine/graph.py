from langgraph.graph import StateGraph, END
from typing import TypedDict, List
from .store import DuckDBStore
import json
import os

class GraphState(TypedDict):
    question: str
    space_id: str
    target_doc: str # Optional document filter
    context: List[str]
    answer: str
    citations: List[dict]

class GraphRAG:
    def __init__(self, store: DuckDBStore, embedding_model=None):
        self.store = store
        self.embedding_model = embedding_model
        self._ensure_model_exists()
        self.workflow = self._build_workflow()

    def _ensure_model_exists(self):
        """
        Check if local LLM model exists, download if not.
        """
        from django.conf import settings
        config = settings.GRAPHRAG_CONFIG
        
        # Only check if OpenAI key is NOT set (prioritize OpenAI)
        # Or check always to be ready for fallback? Let's check always as it was requested to be "default".
        
        model_path = config["LLM_MODEL_PATH"]
        if not os.path.exists(model_path):
            print(f"DEBUG: Model not found at {model_path}. Attempting download...")
            try:
                from huggingface_hub import hf_hub_download
                
                # Ensure directory exists
                os.makedirs(os.path.dirname(model_path), exist_ok=True)
                
                repo_id = config.get("LLM_HF_REPO_ID", "bartowski/Qwen2.5-7B-Instruct-GGUF")
                filename = config.get("LLM_HF_FILENAME", "Qwen2.5-7B-Instruct-Q4_K_M.gguf")
                
                # Download model from configured repo
                print(f"DEBUG: Downloading {filename} from {repo_id}...")
                downloaded_path = hf_hub_download(
                    repo_id=repo_id,
                    filename=filename,
                    local_dir=os.path.dirname(model_path)
                )
                print(f"DEBUG: Downloaded to {downloaded_path}")
            except ImportError:
                print("DEBUG: huggingface_hub not installed. Cannot auto-download.")
            except Exception as e:
                print(f"DEBUG: Model download failed: {e}")
                print("DEBUG: You can manually download from: https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF")
        else:
            print(f"DEBUG: Local LLM found at {model_path}")

    def _build_workflow(self):
        workflow = StateGraph(GraphState)

        # Nodes
        workflow.add_node("retrieve", self.retrieve)
        workflow.add_node("generate", self.generate)

        # Edges
        workflow.set_entry_point("retrieve")
        workflow.add_edge("retrieve", "generate")
        workflow.add_edge("generate", END)

        return workflow.compile()

    def retrieve(self, state: GraphState):
        """Retrieve relevant context from vector store"""
        question = state["question"]
        space_id = state["space_id"]
        # Check for document filter in state (passed via invoke)
        target_doc = state.get("target_doc") 
        
        # Validate question is not empty
        if not question or not question.strip():
            return {"context": [], "citations": []}
        
        # 1. Vector Search
        if self.embedding_model:
            query_vec = self.embedding_model.embed_query(question.strip())
        else:
            # Fallback to mock if no model provided (though views.py should provide it)
            print("WARNING: No embedding model provided to GraphRAG. Using mock embedding.")
            query_vec = [0.1] * 384 
        
        # Pass filter to store search
        # This ensures we get top K results *from the specific document* if filtered
        vector_results = self.store.search_vectors(query_vec, space_id, k=5, text_query=question, target_doc=target_doc)
        
        context = []
        citations = []
        entities_found = []

        for res in vector_results:
            content, meta_json, score = res
            meta = json.loads(meta_json)
            
            # Filtering is now done in DB, so we don't need to filter here
                
            context.append(content)
            citations.append(meta)
            
            # Extract entities from content to query graph
            words = content.split()
            entities = [w.strip(".,") for w in words if w[0].isupper() and len(w) > 3]
            entities_found.extend(entities)

        # 2. Graph Traversal (1-hop)
        if entities_found:
            graph_results = self.store.get_graph_context(list(set(entities_found))[:5]) # Limit to top 5 entities
            for src, tgt, label in graph_results:
                context.append(f"{src} is {label} to {tgt}")

        # Deduplicate citations
        unique_citations = []
        seen_sources = set()
        for c in citations:
            src = c.get('source')
            if src and src not in seen_sources:
                unique_citations.append(c)
                seen_sources.add(src)

        return {"context": context, "citations": unique_citations}

    def generate(self, state: GraphState):
        from django.conf import settings
        config = settings.GRAPHRAG_CONFIG

        context_list = state["context"]
        question = state["question"]
        target_doc = state.get("target_doc")
        
        # Determine if searching specific document or all documents
        is_specific_doc = target_doc and target_doc != "all"
        
        # Check if we have sufficient context
        if not context_list or len(context_list) == 0:
            if is_specific_doc:
                return {"answer": "I couldn't find any relevant information in this specific document to answer your question. The document may not contain information related to your query."}
            else:
                return {"answer": "I couldn't find any relevant information in the uploaded documents to answer your question. Please try rephrasing your question or upload more relevant documents."}
        
        # Deduplicate context lines for cleaner prompt/output
        unique_context = list(dict.fromkeys(context_list))
        context_str = "\n".join(unique_context)
        
        # Check if context is too short (likely low quality match)
        # Instead of refusing, we'll answer but add a warning note
        has_limited_context = len(context_str.strip()) < 50
        warning_note = ""
        
        if has_limited_context:
            if is_specific_doc:
                warning_note = "\n\n**Note:** I found very limited information in this document related to your question. The answer above may be incomplete or not fully address your query."
            else:
                warning_note = "\n\n**Note:** I found very limited information related to your question. The answer above may be incomplete. Consider rephrasing your question or uploading more relevant documents."
        
        # 1. Try OpenAI or Compatible API (if API key is set)
        api_key = config["OPENAI_API_KEY"]
        api_base = config["OPENAI_API_BASE"] # Support for remote local LLMs (vLLM, TGI, etc.)
        model_name = config["LLM_MODEL_NAME"] # Configurable model name
        
        print(f"DEBUG: Checking OpenAI/Remote... Key present: {bool(api_key)}, Base: {api_base}, Model: {model_name}")
        if api_key:
            try:
                from langchain_openai import ChatOpenAI
                from langchain_core.prompts import ChatPromptTemplate
                
                # Allow custom base URL for local inference servers
                llm = ChatOpenAI(
                    model=model_name, 
                    temperature=0, 
                    streaming=True,
                    base_url=api_base if api_base else None
                )
                # Updated prompt to be more strict about using only provided context
                prompt = ChatPromptTemplate.from_template(
                    "Answer the question based ONLY on the following context. If the context does not contain enough information to answer the question, respond with 'I cannot find sufficient information in the provided documents to answer this question.'\n\nContext:\n{context}\n\nQuestion: {question}\n\nAnswer:"
                )
                chain = prompt | llm
                
                # Create a generator that appends the warning note at the end
                def stream_with_note():
                    for chunk in chain.stream({"context": context_str, "question": question}):
                        yield chunk
                    if warning_note:
                        yield warning_note
                
                return {"answer": stream_with_note()}
            except Exception as e:
                print(f"DEBUG: OpenAI/Remote generation failed: {e}")
                # Fall through to local LLM
        
        # 2. Try Local LLM (LlamaCpp)
        try:
            from llama_cpp import Llama, GGML_TYPE_Q8_0
            # This assumes model is at a fixed path or env var
            model_path = config["LLM_MODEL_PATH"]
            gpu_layers = config["LLM_GPU_LAYERS"] # Default to 0 (CPU), set to -1 for all layers on GPU
            
            print(f"DEBUG: Checking Local LLM... Path: {model_path}, Exists: {os.path.exists(model_path)}")
            
            if os.path.exists(model_path):
                # Use configured context size (defaults to 8192 for safety)
                llm = Llama(
                    model_path=model_path, 
                    verbose=False,  # Disable verbose llama.cpp logs
                    n_ctx=config.get("LLM_CONTEXT_SIZE", 8192),
                    n_gpu_layers=gpu_layers, # Enable GPU offloading
                    type_k=GGML_TYPE_Q8_0,
                    type_v=GGML_TYPE_Q8_0,
                    flash_attn=True
                )
                # Updated prompt to be more strict
                prompt = f"""Answer the question based ONLY on the following context. If the context does not contain enough information to answer the question, respond with 'I cannot find sufficient information in the provided documents to answer this question.'

Context:
{context_str}

Question: {question}

Answer:"""
                
                # Create a generator for LlamaCpp
                stream = llm(prompt, max_tokens=256, stop=["Question:", "\n"], echo=False, stream=True)
                
                def local_generator():
                    for chunk in stream:
                        text = chunk['choices'][0]['text']
                        yield text
                    # Append warning note if context was limited
                    if warning_note:
                        yield warning_note
                        
                return {"answer": local_generator()}
            else:
                print(f"DEBUG: Local model still not found at {model_path}")
        except ImportError:
             print("DEBUG: llama-cpp-python not installed or import failed.")
        except Exception as e:
            print(f"DEBUG: Local LLM generation failed: {e}")

        # 3. Fallback: Improved Context Dump (Yield as single chunk)
        if not context_str:
            answer = "I couldn't find any relevant information in the documents."
        else:
            # Format context nicely
            formatted_context = "\n\n".join([f"- {line}" for line in unique_context[:5]]) # Limit to top 5 unique chunks
            answer = f"**Context Found:**\n\n{formatted_context}\n\n*(Note: No active LLM found. Showing retrieved context directly.)*"
        
        # Yield the fallback answer as a single chunk
        def fallback_generator():
            yield answer
            
        return {"answer": fallback_generator()}

    def run(self, question, space_id, target_doc=None):
        inputs = {
            "question": question, 
            "space_id": space_id, 
            "target_doc": target_doc,
            "context": [], 
            "answer": "", 
            "citations": []
        }
        return self.workflow.invoke(inputs)
