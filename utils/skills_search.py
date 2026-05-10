"""
Skills Search - Semantic Search using ChromaDB for Skills
ทำให้ AI สามารถค้นหาและใช้ skills ที่เกี่ยวข้องกับคำถามได้
"""
import os
import logging
from typing import List, Dict, Optional
import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)


class SkillsSearch:
    """Semantic Search สำหรับ Skills โดยใช้ ChromaDB"""
    
    def __init__(self, chroma_host: Optional[str] = None, chroma_port: Optional[int] = None):
        """
        Initialize Skills Search with ChromaDB
        
        Args:
            chroma_host: ChromaDB host (default from env or localhost)
            chroma_port: ChromaDB port (default from env or 8000)
        """
        self.chroma_host = chroma_host or os.getenv("CHROMA_HOST", "localhost")
        self.chroma_port = chroma_port or int(os.getenv("CHROMA_PORT", "8000"))
        
        # Initialize ChromaDB client
        try:
            self.client = chromadb.HttpClient(
                host=self.chroma_host,
                port=self.chroma_port
            )
            self.collection_name = "skills_collection"
            
            # Get or create collection
            try:
                self.collection = self.client.get_collection(self.collection_name)
                logger.info(f"Skills search loaded existing collection: {self.collection_name}")
            except Exception:
                self.collection = self.client.create_collection(
                    name=self.collection_name,
                    metadata={"description": "Skills Semantic Search"}
                )
                logger.info(f"Skills search created new collection: {self.collection_name}")
                
            self.available = True
        except Exception as e:
            logger.warning(f"Skills search initialization failed: {e}")
            self.available = False
            self.collection = None
    
    def add_skill(self, topic: str, summary: str, category: str = "general", source: str = "unknown"):
        """
        Add a skill to the search index
        
        Args:
            topic: Skill topic/name
            summary: Skill summary/description
            category: Skill category (e.g., python, docker, git)
            source: Source of the skill
        """
        if not self.available or not self.collection:
            logger.warning("Skills search not available, skipping add_skill")
            return
        
        try:
            skill_id = f"skill_{topic.replace(' ', '_').lower()}"
            self.collection.upsert(
                ids=[skill_id],
                documents=[f"{topic}: {summary}"],
                metadatas=[{"topic": topic, "category": category, "source": source}],
            )
            logger.info(f"Upserted skill: {topic}")
        except Exception as e:
            logger.error(f"Failed to upsert skill: {e}")
    
    def add_skills_from_db(self, skills_db: Dict):
        """
        Add all skills from skills_db.json to the search index
        
        Args:
            skills_db: Dictionary of skills from skills_db.json
        """
        if not self.available or not self.collection:
            logger.warning("Skills search not available, skipping add_skills_from_db")
            return
        
        for topic, data in skills_db.items():
            self.add_skill(
                topic=topic,
                summary=data.get("summary", ""),
                category="learned",
                source=data.get("source", "unknown")
            )
    
    def search(self, query: str, n_results: int = 3, category: Optional[str] = None) -> List[Dict]:
        """
        Search for relevant skills based on query
        
        Args:
            query: Search query
            n_results: Number of results to return
            category: Filter by category (optional)
        
        Returns:
            List of relevant skills with metadata
        """
        if not self.available or not self.collection:
            logger.warning("Skills search not available, returning empty results")
            return []
        
        try:
            # Build filter if category is specified
            where_filter = None
            if category:
                where_filter = {"category": category}
            
            # Search
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter
            )
            
            # Format results
            skills = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    skills.append({
                        "topic": results['metadatas'][0][i]['topic'],
                        "summary": doc,
                        "category": results['metadatas'][0][i]['category'],
                        "source": results['metadatas'][0][i]['source'],
                        "distance": results['distances'][0][i] if 'distances' in results else None
                    })
            
            logger.info(f"Skills search for '{query}' returned {len(skills)} results")
            return skills
        except Exception as e:
            logger.error(f"Skills search failed: {e}")
            return []
    
    def get_all_categories(self) -> List[str]:
        """Get all unique skill categories"""
        if not self.available or not self.collection:
            return []
        
        try:
            # Get all documents and extract unique categories
            results = self.collection.get()
            categories = set()
            for metadata in results.get('metadatas', []):
                if 'category' in metadata:
                    categories.add(metadata['category'])
            return list(categories)
        except Exception as e:
            logger.error(f"Failed to get categories: {e}")
            return []


# Global instance
_skills_search = None


def get_skills_search() -> SkillsSearch:
    """Get or create global SkillsSearch instance"""
    global _skills_search
    if _skills_search is None:
        _skills_search = SkillsSearch()
    return _skills_search


def sync_skills_to_search(skills_db: Dict):
    """
    Sync skills from skills_db.json to ChromaDB search index
    This should be called when skills are updated
    """
    search = get_skills_search()
    if search.available:
        search.add_skills_from_db(skills_db)
        logger.info(f"Synced {len(skills_db)} skills to search index")
