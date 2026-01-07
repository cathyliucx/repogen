# AST Call Graph Analysis Tool

This tool provides functionality to analyze Python codebases by building and querying call graphs using Abstract Syntax Tree (AST) parsing. It helps in understanding code relationships and dependencies between functions, methods, and classes with advanced semantic support.

## 🚀 Key Improvements over Original Version

- **Semantic Inheritance Resolution**: Unlike the original name-based matching, this version recursively traverses Class Bases (MRO) to find inherited method implementations.
- **Universal Python Compatibility**: Rely on dependency on `end_lineno` (Python 3.8+) or a custom recursive boundary detection algorithm(< Python 3.8), supporting all Python environments.
- **Zero-Redundancy Caching**: Integrated a dual-layer cache (`_ast_cache` & `_source_cache`) that reduces disk IO by up to 90% in large-scale repository scans.
- **Context-Aware `self` Parsing**: Intelligent tracking of enclosing class scopes to correctly resolve internal method calls.
- **Decorator Integrity**: Automatically adjusts source capture to include function and class decorators, which were previously truncated.

## Features

### Call Graph Building
- **Repository-Wide Analysis**: Automatically builds a complete call graph for a Python repository.
- **Cross-File Dependencies**: Tracks relationships across different modules and packages.
- **Optimized Performance**: Implements internal AST and source-line caching to prevent redundant disk IO.
- **Universal Version Support**: Features a custom recursive line-number calculator for compatibility with Python versions older than 3.8.

## Code Component Analysis

The tool provides specialized functionalities for granular code retrieval:

1. **Child Function Analysis** (`get_child_function`)
   - **Input**: Component node, AST tree, and dependency path.
   - **Output**: Full source code of the function being called.
   - **Use Case**: Finding implementation of functions called within your code, including cross-module imports.

2. **Child Method Analysis** (`get_child_method`)
   - **Input**: Component node, AST tree, and dependency path.
   - **Output**: Full source code of the method being called.
   - **Use Case**: Finding implementations of methods. **New**: If a method is not found in the immediate class, the tool recursively searches through the inheritance hierarchy (MRO).

3. **Child Class Analysis** (`get_child_class_init`)
   - **Input**: Component node, AST tree, and dependency path.
   - **Output**: Class signature and the complete `__init__` method code.
   - **Use Case**: Finding class definitions and setup logic for instantiated objects without retrieving the entire class body.

4. **Parent Component Analysis** (`get_parent_components`)
   - **Input**: Component node, AST tree, dependency path, and a dependency graph.
   - **Output**: A list of full code snippets for all components that call or depend on the target.
   - **Use Case**: Global reverse-lookup to identify which functions or classes depend on a specific component.

5. **Contextual Analysis** (Internal logic)
   - **Input**: Internal AST node and tree.
   - **Output**: Resolved class context for `self` references.
   - **Use Case**: Correcting paths that use `self.method()` to point to the actual class implementation.

6. **Source Recovery & Compatibility**
   - **Input**: Target AST node and source lines.
   - **Output**: Cleanly extracted code blocks, including decorators (`@decorator`).
   - **Use Case**: Ensuring code snippets are complete and accurate across all Python 3.x versions by using a recursive fallback for `end_lineno`.

## Usage Example

```python
from agent.tool.ast import ASTNodeAnalyzer

# Initialize the analyzer with repository path
analyzer = ASTNodeAnalyzer("/path/to/repo")

# Find a method implementation (even if it is inherited from a parent class)
child_code = analyzer.get_child_method(
    focal_node,
    full_ast_tree,
    "services.worker.SmartWorker.execute"
)

# Find what functions a component calls
func_code = analyzer.get_child_function(
    focal_node,
    full_ast_tree,
    "utils.helper.format_result"
)
```
## Implementation Details
- AST Engine: Uses Python's built-in ast module for non-executing static code parsing.
- Caching Layer: Maintains _ast_cache and _source_cache for high-speed analysis and reduced IO overhead.
- Hierarchy Traversal: Recursively checks bases in ClassDef nodes to support single and multiple inheritance patterns.
- Decorator Handling: Dynamically calculates start lines by inspecting decorator_list to ensure full source capture.
- Recursive Boundary Detection: Implements a custom algorithm to determine the end of a code block by traversing all child nodes, ensuring stability when end_lineno is missing.
- Construct Support:
    - Function and Async function definitions.
    - Class definitions and instantiations.
    - Method calls (direct, self, and inherited).
    - Cross-file dependency resolution and module path mapping.

## Limitations
- Language Support: Currently only supports Python files (.py).
- Static Analysis: Does not handle dynamic code execution or runtime modifications (e.g., eval(), exec(), or dynamic setattr()).
- Inheritance Scope: Inheritance resolution is limited to classes and parent structures defined within the indexed repository path.
- Type Resolution: Complex dynamic type resolution (e.g., objects passed as arguments without explicit type hints) may fall back to name-based heuristic matching.