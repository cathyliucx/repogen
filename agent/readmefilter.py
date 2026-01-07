from pathlib import Path
import sys
from .base import BaseAgent
from typing import Optional
import json
import re

class ReadmeFilterAgent(BaseAgent):
    """
    Agent specialized in determining if a GitHub repository aligns with 
    financial or specific business requirements based on its README.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        # The name 'repo_filter' matches the key under 'agent_llms' in your YAML config
        super().__init__(name="repo_filter", config_path=config_path)

    def process(self, readme_content: str) -> bool:
        """
        Processes the README content and returns a boolean indicating 
        whether the repository should be kept.
        """
        
        # Construct Prompts
        system_prompt = (
            "You are a financial industry expert. Your task is to filter GitHub "
            "repositories and identify those related to banking, payments, "
            "quantitative trading, insurance, and other financial services."
        )
        
        user_prompt = (
            "Please read the following README content and determine if this project "
            "belongs to the financial industry. You must return only a JSON object: "
            '{"is_financial": true/false}.\n\n'
            f"Content:\n{readme_content[:1000]}"
        )

        # Utilize BaseAgent's memory and generation capabilities
        self.clear_memory()
        self.add_to_memory("system", system_prompt)
        self.add_to_memory("user", user_prompt)
        
        try:
            # Generate response via the LLM defined in BaseAgent
            response = self.generate_response()
            # Decision Logic
            # We use a case-insensitive check for the specific JSON key-value pair
            # This is more robust than full JSON parsing if the LLM adds markdown formatting
            return '"is_financial": true' in response.lower()
            
        except Exception as e:
            print(f"Agent processing error for {self.name}: {e}")
            # Default to False on failure (reject-by-default)
            return False