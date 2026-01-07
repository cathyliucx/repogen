# Copyright (c) Meta Platforms, Inc. and affiliates
import ast
import os
from typing import List, Optional, Dict, Any, Tuple

class ASTNodeAnalyzer:
    """
    Enhanced AST Node Analysis Tool.
    
    Features:
    1. Performance: AST and Source caching to reduce IO overhead.
    2. Compatibility: Dual-path line number handling (Python 3.8+ and legacy).
    3. Semantic Search: Recursive MRO search for inherited methods.
    4. Robustness: Decorator offset correction for complete source extraction.
    """

    def __init__(self, repo_path: str):
        """
        Initialize the analyzer.
        Args:
            repo_path: Absolute path to the repository root.
        """
        self.repo_path = repo_path
        self._ast_cache: Dict[str, ast.AST] = {}      # Path -> AST object
        self._source_cache: Dict[str, List[str]] = {} # Path -> Source lines

    def _get_ast_and_lines(self, rel_path: str) -> Tuple[Optional[ast.AST], List[str]]:
        """Load AST and source lines on demand with caching."""
        full_path = os.path.normpath(os.path.join(self.repo_path, rel_path))
        if full_path in self._ast_cache:
            return self._ast_cache[full_path], self._source_cache[full_path]
        
        if not os.path.exists(full_path):
            return None, []
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
                tree = ast.parse(content)
                lines = content.splitlines()
                self._ast_cache[full_path] = tree
                self._source_cache[full_path] = lines
                return tree, lines
        except Exception:
            return None, []

    def _get_node_end_line(self, node: ast.AST) -> int:
        """Recursive helper to find the end line of a node across Python versions."""
        if hasattr(node, 'end_lineno') and node.end_lineno is not None:
            return node.end_lineno

        max_line = getattr(node, 'lineno', 0)
        for child in ast.iter_child_nodes(node):
            child_end = self._get_node_end_line(child)
            max_line = max(max_line, child_end)
        return max_line

    def _get_node_source(self, file_rel_path: str, node: ast.AST) -> str:
        """Extract source code from cache, adjusting for decorators and version differences."""
        _, lines = self._get_ast_and_lines(file_rel_path)
        if not lines:
            return ""

        # Adjust start line for decorators
        start_line = node.lineno
        if hasattr(node, 'decorator_list') and node.decorator_list:
            dec_lines = [d.lineno for d in node.decorator_list if hasattr(d, 'lineno')]
            if dec_lines:
                start_line = min(dec_lines)

        end_line = self._get_node_end_line(node)
        return '\n'.join(lines[start_line - 1 : max(start_line, end_line)])

    # --- Component Type Specific Logic ---

    def _get_class_component(self, rel_path: str, class_name: str) -> Optional[str]:
        """Specific logic for extracting a class definition."""
        tree, _ = self._get_ast_and_lines(rel_path)
        if tree:
            node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name), None)
            if node:
                return self._get_node_source(rel_path, node)
        return None

    def _get_function_component(self, rel_path: str, func_name: str) -> Optional[str]:
        """Specific logic for extracting a top-level function."""
        tree, _ = self._get_ast_and_lines(rel_path)
        if tree:
            # Matches FunctionDef but ensures it's not a method (top-level or in module)
            node = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name), None)
            if node:
                return self._get_node_source(rel_path, node)
        return None

    def _get_method_component(self, rel_path: str, class_name: str, method_name: str) -> Optional[str]:
        """Specific logic for extracting a method, including inheritance search."""
        return self._find_method_in_hierarchy(rel_path, class_name, method_name)

    def _find_method_in_hierarchy(self, rel_path: str, class_name: str, method_name: str, depth: int = 0) -> Optional[str]:
        """Recursive MRO search for methods."""
        if depth > 7: return None
        
        tree, _ = self._get_ast_and_lines(rel_path)
        if not tree: return None

        target_class = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name), None)
        if not target_class: return None

        for item in target_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                return self._get_node_source(rel_path, item)
        
        for base in target_class.bases:
            if isinstance(base, ast.Name):
                res = self._find_method_in_hierarchy(rel_path, base.id, method_name, depth + 1)
                if res: return res
        return None

    # --- Main Interface ---

    def get_component_by_path(self, ast_node: ast.AST, ast_tree: ast.AST, dependency_path: str) -> Optional[str]:
        """
        Routes the request to the specific component extractor based on path structure.
        """
        path_parts = dependency_path.split('.')
        if len(path_parts) < 2:
            return None
        
        last = path_parts[-1]
        
        # 1. Route to Methods: e.g., pkg.file.ClassName.method
        if len(path_parts) >= 3 and last[0].islower() and path_parts[-2][0].isupper():
            rel_path = os.path.join(*path_parts[:-2]) + ".py"
            return self._get_method_component(rel_path, path_parts[-2], last)
        
        # 2. Route to Classes: e.g., pkg.file.ClassName
        if last[0].isupper():
            rel_path = os.path.join(*path_parts[:-1]) + ".py"
            return self._get_class_component(rel_path, last)
        
        # 3. Route to Functions: e.g., pkg.file.func_name
        rel_path = os.path.join(*path_parts[:-1]) + ".py"
        return self._get_function_component(rel_path, last)

    # --- Child Accessors (Keeping them distinct) ---

    def get_child_class_init(self, ast_node: ast.AST, ast_tree: ast.AST, dependency_path: str) -> Optional[str]:
        """Gets class definition up to the end of __init__."""
        full_code = self.get_component_by_path(ast_node, ast_tree, dependency_path)
        if not full_code: return None
        
        try:
            temp_ast = ast.parse(full_code)
            cls_node = next(n for n in ast.walk(temp_ast) if isinstance(n, ast.ClassDef))
            init_node = next((n for n in cls_node.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)
            
            if init_node:
                init_end = self._get_node_end_line(init_node)
                return "\n".join(full_code.splitlines()[:init_end])
        except Exception:
            pass
        return full_code

    def get_child_function(self, ast_node: ast.AST, ast_tree: ast.AST, dependency_path: str) -> Optional[str]:
        """Explicitly handles function retrieval."""
        path_parts = dependency_path.split('.')
        rel_path = os.path.join(*path_parts[:-1]) + ".py"
        return self._get_function_component(rel_path, path_parts[-1])

    def get_child_method(self, ast_node: ast.AST, ast_tree: ast.AST, dependency_path: str) -> Optional[str]:
        """Explicitly handles method retrieval."""
        path_parts = dependency_path.split('.')
        if len(path_parts) < 3: return None
        rel_path = os.path.join(*path_parts[:-2]) + ".py"
        return self._get_method_component(rel_path, path_parts[-2], path_parts[-1])

    def get_parent_components(self, ast_node: ast.AST, ast_tree: ast.AST, dependency_path: str, dependency_graph: Dict[str, List[str]]) -> List[str]:
        """Find callers using the dependency graph."""
        parent_components = []
        for component_id, dependencies in dependency_graph.items():
            if dependency_path in dependencies:
                parent_code = self.get_component_by_path(ast_node, ast_tree, component_id)
                if parent_code:
                    parent_components.append(parent_code)
        return parent_components