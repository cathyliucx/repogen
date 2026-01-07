from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..base import BaseAgent
from ..utils import strip_think_blocks


class CodeComponentType(Enum):
    """Enum for different types of code components."""

    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"


@dataclass
class InformationRequest:
    """Data class for structured information requests."""

    internal_requests: List[str]
    external_requests: List[str]


class Reader(BaseAgent):
    """Agent responsible for determining if more context is needed for docstring generation."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the Reader agent.

        Args:
            config_path: Optional path to the configuration file
        """
        super().__init__("Reader", config_path)
        self.system_prompt = """You are a Reader agent responsible for determining if more context
is needed to generate high-quality, business-oriented Question-Answer (QA) pairs AND to 
generate a design solution based on the local codebase architecture. 

You must analyze the code component and the current context to determine if the business 
logic, architectural patterns, and system constraints are fully understood.

You have access to two types of information sources:

1. Internal Codebase Information (from local code repository):
    For Functions:
    - Code components called within the function body (Downstream logic)
    - Places where this function is called (Upstream business triggers)

    For Methods:
    - Code components called within the method body
    - Places where this method is called
    - The class this method belongs to (Inheritance and shared state)

    For Classes:
    - Code components called in the __init__ method (Dependency Injections)
    - Places where this class is instantiated (Lifecycle management)
    - Complete class implementation beyond __init__

2. External Repo Business Logic Summary:
    - High-level architecture designs (e.g., Microservices, Layered, Event-driven).
    - Global business rules, domain-driven designs, and cross-module workflows.
    - Standardized patterns used across the repo (e.g., error handling strategies, auth flows).

Your response should:
1. First provide a free text analysis of the current code and context from BOTH business and architecture perspective.
2. Explain what additional information might be needed to answer "Why" and "For whom" the code executes if needed.
3. Include an <INFO_NEED>true</INFO_NEED> tag if more information is needed,
    or <INFO_NEED>false</INFO_NEED> if current context is sufficient.
4. If more information is needed, end your response with a structured request in XML format:

<ANALYSIS>
    <BUSINESS_LOGIC>
    Business logic analysis.
    <\BUSINESS_LOGIC>
    <ARCHITECTURE_PATTERNS>
    Repository architecture patterns analysis.
    <\ARCHITECTURE_PATTERNS>
</ANALYSIS>

<REQUEST>
    <INTERNAL>
        <CALLS>
            <CLASS>class1,class2</CLASS>
            <FUNCTION>func1,func2</FUNCTION>
            <METHOD>self.method1,instance.method2</METHOD>
        </CALLS>
        <CALL_BY>true/false</CALL_BY>
    </INTERNAL>
    <RETRIEVAL>
        <QUERY>Natural language question </QUERY>
    </RETRIEVAL>
</REQUEST>

Important rules for structured request:
1. Only request information necessary for understanding business logic and architecture patterns.
2. For CALLS sections, only include names that are explicitly needed to clarify data flow.
3. CALL_BY should be "true" only if the business trigger/caller reveals the purpose of the code.
4. Each RETRIEVAL QUERY should focus on uncovering hidden business constraints or domain-specific logic.
5. Only first-level calls of the focal code component are accessible.

Format Contract:
1. Output MUST contain exactly these tags in this order:
<ANALYSIS>
</ANALYSIS>
<INFO_NEED>true|false</INFO_NEED>
If and only if INFO_NEED is true, output:
<REQUEST>
  <INTERNAL>
    <CALLS>
      <CLASS>...</CLASS>
      <FUNCTION>...</FUNCTION>
      <METHOD>...</METHOD>
    </CALLS>
    <CALL_BY>true|false</CALL_BY>
  </INTERNAL>
  <RETRIEVAL>
    <QUERY>...</QUERY>
  </RETRIEVAL>
</REQUEST>

2. In <CALLS>, <CLASS>, <FUNCTION>, <METHOD> MUST ALL exist exactly once even if empty:
- If none, output empty tag text: <CLASS></CLASS> etc.
- DO NOT add extra tags (no additional <FUNCTION> tags, no <METHOD> repeated tags).

3. The text inside <CLASS>/<FUNCTION>/<METHOD> MUST be a single line comma-separated list (ASCII comma “,”).
- Example: <FUNCTION>foo,bar,baz</FUNCTION>
- No newlines, no bullets, no numbering.
- If there are multiple candidates, include at most 6 items.

4. <QUERY> MUST appear exactly once.
- If you need multiple questions, merge them into ONE sentence separated by semicolons inside the same <QUERY> tag.

5. Do not include any XML tags other than those specified above.

<Example_response>
<ANALYSIS> 
The current code implements the validate_transaction method. While it invokes the CheckBlacklist function, 
the specific business criteria that define a "blacklisted" entity (e.g., velocity limits, IP reputation, or specific user status) 
are absent from the context. To generate accurate QA pairs regarding risk policies, we must understand these specific rules. 
The system appears to follow a Middleware or Interceptor pattern, where security checks are decoupled from core transaction 
processing. CheckBlacklist is likely an external dependency or part of a shared SecurityProvider module. Identifying its 
location is crucial for understanding the repository's dependency injection and cross-cutting concern management. 
</ANALYSIS>

<INFO_NEED>true</INFO_NEED>

<REQUEST>
    <INTERNAL>
        <CALLS>
            <CLASS></CLASS>
            <FUNCTION>CheckBlacklist</FUNCTION>
            <METHOD></METHOD>
        </CALLS>
        <CALL_BY>true</CALL_BY>
    </INTERNAL>
    <RETRIEVAL>
        <QUERY>What are the specific business criteria for blacklisting a transaction in this system?</QUERY>
    </RETRIEVAL>
</REQUEST>
</Example_response>

Keep in mind that:

3. You do not need to complete the generation task. Just determine if more information is needed.
"""

        self.add_to_memory("system", self.system_prompt)

    def process(self, focal_component: str, context: str = "") -> str:
        """Process the input and determine if more context is needed.

        Args:
            instruction: The instruction for docstring generation
            focal_component: The code component needing to get business logic
            component_type: The type of the code component (function, method, or class)
            context: Current context information (if any)

        Returns:
            A string containing the analysis and <INFO_NEED> tag indicating if more information is needed
        """
        # Add the current task to memory
        task_description = f"""
        <context>
        Current context:
        {context if context else 'No context provided yet.'}
        </context>

        <component>
        Analyze the following code component:

        {focal_component}
        </component>
        """
        self.add_to_memory("user", task_description)

        # Generate response using LLM
        response = strip_think_blocks(self.generate_response())
        return response
