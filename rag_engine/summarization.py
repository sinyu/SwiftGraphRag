"""
Helper functions for document summarization and analysis.
"""
from django.conf import settings

def generate_summary(text: str, max_length: int = 500) -> str:
    """
    Generate a concise summary of the given text using LLM.
    
    Args:
        text: The text to summarize
        max_length: Maximum length of summary in tokens
        
    Returns:
        A concise summary of the text
    """
    config = settings.GRAPHRAG_CONFIG
    
    # Truncate text if too long (keep first ~4000 chars for context)
    if len(text) > 4000:
        text = text[:4000] + "..."
    
    prompt = f"""Provide a concise summary of the following document. Focus on the main topics, key points, and important information.

Document:
{text}

Summary:"""
    
    # Try OpenAI/Remote API first
    api_key = config.get("OPENAI_API_KEY")
    if api_key:
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.prompts import ChatPromptTemplate
            
            llm = ChatOpenAI(
                model=config.get("LLM_MODEL_NAME", "gpt-3.5-turbo"),
                temperature=0.3,
                max_tokens=max_length,
                base_url=config.get("OPENAI_API_BASE") if config.get("OPENAI_API_BASE") else None
            )
            
            prompt_template = ChatPromptTemplate.from_template(
                "Provide a concise summary of the following document. Focus on the main topics, key points, and important information.\n\nDocument:\n{text}\n\nSummary:"
            )
            
            chain = prompt_template | llm
            result = chain.invoke({"text": text})
            
            # Extract content from AIMessage
            if hasattr(result, 'content'):
                return result.content.strip()
            return str(result).strip()
            
        except Exception as e:
            print(f"OpenAI summarization failed: {e}")
    
    # Try local LLM
    try:
        from llama_cpp import Llama, GGML_TYPE_Q8_0
        import os
        
        model_path = config.get("LLM_MODEL_PATH")
        if model_path and os.path.exists(model_path):
            llm = Llama(
                model_path=model_path,
                n_ctx=config.get("LLM_CONTEXT_SIZE", 8192),
                n_gpu_layers=config.get("LLM_GPU_LAYERS", 0),
                verbose=False
            )
            
            response = llm(prompt, max_tokens=max_length, temperature=0.3, stop=["Document:", "\n\n"])
            return response['choices'][0]['text'].strip()
            
    except Exception as e:
        print(f"Local LLM summarization failed: {e}")
    
    # Fallback: Return first 500 characters
    return text[:500] + "..." if len(text) > 500 else text


def extract_entities(text: str) -> list:
    """
    Extract key entities (people, organizations, concepts) from text.
    
    Args:
        text: The text to analyze
        
    Returns:
        List of extracted entities
    """
    config = settings.GRAPHRAG_CONFIG
    
    # Truncate text if too long
    if len(text) > 2000:
        text = text[:2000] + "..."
    
    prompt = f"""Extract the key entities from the following text. List people, organizations, locations, and important concepts.
Format: Return only a comma-separated list of entities.

Text:
{text}

Entities:"""
    
    # Try OpenAI/Remote API
    api_key = config.get("OPENAI_API_KEY")
    if api_key:
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.prompts import ChatPromptTemplate
            
            llm = ChatOpenAI(
                model=config.get("LLM_MODEL_NAME", "gpt-3.5-turbo"),
                temperature=0,
                max_tokens=200,
                base_url=config.get("OPENAI_API_BASE") if config.get("OPENAI_API_BASE") else None
            )
            
            prompt_template = ChatPromptTemplate.from_template(prompt)
            result = llm.invoke(prompt_template.format())
            
            # Extract content and parse entities
            content = result.content if hasattr(result, 'content') else str(result)
            entities = [e.strip() for e in content.split(',') if e.strip()]
            return entities[:20]  # Limit to 20 entities
            
        except Exception as e:
            print(f"Entity extraction failed: {e}")
    
    # Fallback: Return empty list
    return []
