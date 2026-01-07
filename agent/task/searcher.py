import os
import re
import ast
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# Internal imports
from ..base import BaseAgent
from ..tool.internal_traverse import ASTNodeAnalyzer

# LangChain imports for Local RAG
from langchain_community.document_loaders import TextLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ..utils import strip_think_blocks

@dataclass
class ParsedInfoRequest:
    internal_requests: Dict[str, Any] = field(default_factory=lambda: {
        'call': {
            'class': [],
            'function': [], 
            'method': []
        },
        'call_by': False
    })
    external_requests: List[str] = field(default_factory=list)

class Searcher(BaseAgent):
    """Agent responsible for gathering requested information from internal AST and local RAG sources."""

    def __init__(self, repo_path: str, rag_path: Optional[str] = None, config_path: Optional[str] = None):
        """Initialize the Searcher agent with strict path validation.

        Args:
            repo_path: Path to the repository being analyzed
            rag_path: Path to the knowledge base file (.txt or .md)
            config_path: Optional path to the configuration file

        Returns:
            None
        """
        super().__init__("Searcher", config_path=config_path)
        self.repo_path = repo_path
        self.ast_analyzer = ASTNodeAnalyzer(repo_path)
        
        # 1. Check if the variable is provided (Value Validation)
        if not rag_path:
            raise ValueError(
                "RAG initialization failed: 'rag_path' is empty or None. "
                "Please ensure the path to the knowledge base is correctly passed in arguments."
            )

        # 2. Check if the physical file exists (File System Validation)
        abs_path = os.path.abspath(rag_path)
        if not os.path.exists(rag_path):
            error_msg = (
                f"\n{'='*70}\n"
                f"CRITICAL ERROR: RAG Knowledge Base File Not Found!\n"
                f"Provided Path: {rag_path}\n"
                f"Absolute Path Attempted: {abs_path}\n"
                f"Current Working Directory: {os.getcwd()}\n"
                f"Hint: Check if the file exists or if the relative path is correct.\n"
                f"{'='*70}"
            )
            raise FileNotFoundError(error_msg)

        # 3. Proceed to initialize the RAG pipeline
        self.rag_chain = None
        self._setup_rag(rag_path)

    def _setup_rag(self, rag_path: str):
        """Initializes the local RAG pipeline with Markdown support and recursive splitting.

        Args:
            rag_path: The validated path to the external knowledge base file

        Returns:
            None. Sets the self.rag_chain attribute upon success
        """
        try:
            if rag_path.lower().endswith('.md'):
                loader = UnstructuredMarkdownLoader(rag_path)
            else:
                loader = TextLoader(rag_path)
            
            documents = loader.load()

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=600,
                chunk_overlap=60,
                separators=["\n### ", "\n## ", "\n# ", "\n\n", "\n", " ", ""]
            )
            docs = text_splitter.split_documents(documents)

            embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
            vectorstore = FAISS.from_documents(docs, embeddings)
            
            llm = ChatOpenAI(
                model_name="my-model",             
                openai_api_base="http://localhost:8000/v1", 
                openai_api_key="EMPTY",
                temperature=0.1
            )

            prompt = ChatPromptTemplate.from_template("""
            You are a software expert. Extract business rules and software knowledge from the context 
            to explain the purpose and usage of the code components.
            Answer based ONLY on the following context. If not found, say "Information not found".

            Context:
            {context}

            Question: {question}
            """)

            self.rag_chain = (
                {"context": vectorstore.as_retriever(search_kwargs={"k": 5}), "question": RunnablePassthrough()}
                | prompt
                | llm
                | StrOutputParser()
            )
            print(f"Local RAG system initialized successfully with {len(docs)} chunks.")
            
        except Exception as e:
            raise RuntimeError(f"Failed to build RAG pipeline from {rag_path}: {str(e)}")

    def process(
        self, 
        reader_response: str, 
        ast_node: ast.AST,
        ast_tree: ast.AST,
        dependency_graph: Dict[str, List[str]],
        focal_node_dependency_path: str
    ) -> Dict[str, Any]:
        """Process the reader's response and gather the requested information.

        Args:
            reader_response: Response from the Reader agent containing information requests
            ast_node: AST node representing the focal component
            ast_tree: AST tree for the entire file
            dependency_graph: Dictionary mapping component paths to their dependencies
            focal_node_dependency_path: Dependency path of the focal component

        Returns:
            A dictionary containing both 'internal' (AST) and 'external' (RAG) gathered information
        """
        parsed_request = self._parse_reader_response(reader_response)

        internal_info = self._gather_internal_info(
            ast_node,
            ast_tree,
            focal_node_dependency_path,
            dependency_graph,
            parsed_request
        )

        external_info = self._gather_external_info(parsed_request.external_requests)
        
        return {
            'internal': internal_info,
            'external': external_info
        }

    def _gather_external_info(self, queries: List[str]) -> Dict[str, str]:
        """Internal helper to run RAG queries through the LCEL chain.

        Args:
            queries: List of query strings for external business logic search

        Returns:
            A dictionary mapping each query to its corresponding RAG-generated answer
        """
        if not queries:
            return {}
        if not self.rag_chain:
            return {query: "Information not found (RAG not initialized)" for query in queries}
            
        results = {}
        for query in queries:
            try:
                print(f"Searcher performing RAG query: {query}")
                raw_answer = self.rag_chain.invoke(query)
                results[query] = strip_think_blocks(raw_answer)
            except Exception as e:
                print(f"Error querying local RAG for '{query}': {str(e)}")
                results[query] = f"Error: {str(e)}"
                
        return results

    def _parse_reader_response(self, reader_response: str) -> ParsedInfoRequest:
        """Parse the reader's structured XML response.

        Args:
            reader_response: Response string from the Reader agent containing XML block

        Returns:
            A ParsedInfoRequest object containing structured internal and external requests
        """
        xml_match = re.search(r'<REQUEST>(.*?)</REQUEST>', reader_response, re.DOTALL)
        if not xml_match:
            return ParsedInfoRequest()
            
        xml_content = f'<REQUEST>{xml_match.group(1)}</REQUEST>'
        
        try:
            root = ET.fromstring(xml_content)
            internal = root.find('INTERNAL')
            calls = internal.find('CALLS')
            
            internal_requests = {
                'call': {
                    'class': self._parse_comma_list(calls.find('CLASS').text) if calls.find('CLASS') is not None else [],
                    'function': self._parse_comma_list(calls.find('FUNCTION').text) if calls.find('FUNCTION') is not None else [],
                    'method': self._parse_comma_list(calls.find('METHOD').text) if calls.find('METHOD') is not None else []
                },
                'call_by': (internal.find('CALL_BY').text.lower() == 'true') if internal.find('CALL_BY') is not None else False
            }
            
            external = root.find('RETRIEVAL')
            external_queries = self._parse_comma_list(external.find('QUERY').text) if (external is not None and external.find('QUERY') is not None) else []
            
            return ParsedInfoRequest(
                internal_requests=internal_requests,
                external_requests=external_queries
            )
        except (ET.ParseError, AttributeError) as e:
            print(f"Error parsing XML from Reader: {e}")
            return ParsedInfoRequest()

    def _parse_comma_list(self, text: str | None) -> List[str]:
        """Parse comma-separated text into a list of strings.

        Args:
            text: Input string containing comma-separated items or None

        Returns:
            A list of trimmed, non-empty strings
        """
        if not text:
            return []
        return [item.strip() for item in text.split(',') if item.strip()]

    def _gather_internal_info(
        self, 
        ast_node: ast.AST, 
        ast_tree: ast.AST, 
        focal_dependency_path: str, 
        dependency_graph: Dict[str, List[str]], 
        parsed_request: ParsedInfoRequest
    ) -> Dict[str, Any]:
        """Gather internal code information using the dependency graph and AST analyzer.

        Args:
            ast_node: AST node representing the focal component
            ast_tree: AST tree for the entire file
            focal_dependency_path: Dependency path of the focal component
            dependency_graph: Dictionary mapping component paths to their dependencies
            parsed_request: Structured format of the Reader's information requests

        Returns:
            A dictionary containing code snippets for requested classes, functions, methods, and callers
        """
        result = {
            'calls': {'class': {}, 'function': {}, 'method': {}},
            'called_by': []
        }
        
        component_dependencies = dependency_graph.get(focal_dependency_path, [])
        
        # 1. Classes
        if parsed_request.internal_requests['call']['class']:
            req_classes = parsed_request.internal_requests['call']['class']
            for dep_path in component_dependencies:
                path_parts = dep_path.split('.')
                if path_parts and path_parts[-1][0].isupper():
                    class_name = path_parts[-1]
                    for req in req_classes:
                        if req == class_name or req in dep_path:
                            code = self.ast_analyzer.get_component_by_path(ast_node, ast_tree, dep_path)
                            if code: result['calls']['class'][req] = code
                            break
        # 2. Functions
        if parsed_request.internal_requests['call']['function']:
            req_funcs = parsed_request.internal_requests['call']['function']
            for dep_path in component_dependencies:
                path_parts = dep_path.split('.')
                if path_parts and path_parts[-1][0].islower():
                    if len(path_parts) >= 2 and path_parts[-2][0].isupper():
                        continue
                    func_name = path_parts[-1]
                    for req in req_funcs:
                        if req == func_name or req in dep_path:
                            code = self.ast_analyzer.get_component_by_path(ast_node, ast_tree, dep_path)
                            if code: result['calls']['function'][req] = code
                            break
        # 3. Methods
        if parsed_request.internal_requests['call']['method']:
            req_methods = parsed_request.internal_requests['call']['method']
            for dep_path in component_dependencies:
                path_parts = dep_path.split('.')
                if len(path_parts) >= 2 and path_parts[-1][0].islower() and path_parts[-2][0].isupper():
                    method_name = path_parts[-1]
                    for req in req_methods:
                        if req == method_name or req in dep_path:
                            code = self.ast_analyzer.get_component_by_path(ast_node, ast_tree, dep_path)
                            if code: result['calls']['method'][req] = code
                            break
        # 4. Call_by
        if parsed_request.internal_requests['call_by']:
            parents = self.ast_analyzer.get_parent_components(ast_node, ast_tree, focal_dependency_path, dependency_graph)
            if parents:
                result['called_by'].extend(parents)
            else:
                result['called_by'].append("This component is never called by any other component.")
        
        return result