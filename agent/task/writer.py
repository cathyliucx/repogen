from typing import Dict, Any, Optional, Literal
from ..base import BaseAgent
from ..utils import strip_think_blocks

class Writer(BaseAgent):
    """Agent responsible for generating QA pairs or Design Schemas based on business logic and code context."""
    
    def __init__(self, config_path: Optional[str] = None):
        super().__init__("Writer", config_path=config_path)
        
        # Setting 1: Code comprehension question and answer generation prompt
        self.qa_prompt = """Your task is to generate 3 high-quality QA pairs for the code component 
        based on the provided analysis and code context.

        For each QA pair, you MUST provide:
        1. [Question]: A specific question about business rules, edge cases, or implementation logic.
        2. [Answer]: A clear explanation of the logic.
        3. [Code Snippet]: The EXACT code segment as evidence from the context that implements this logic. 
        You MUST ETRACT the code snippet as a raw string from the context without any modification.
        4. [Reasoning Process]: A trace showing: Business Requirement -> Logic Design -> Code Implementation.

        Output Format:
        Each QA pair must strictly follow this format:
        <QA>
            <Q>Question: A specific inquiry regarding business rules, edge cases, or implementation logic.</Q>
            <A>Answer: A clear and detailed explanation of the logic.</A>
            <CODE>Code Snippet: The exact segment of code implementing this specific logic.</CODE>
            <TRACE>Reasoning Trace: Business Requirement -> Logic Design -> Code Implementation.</TRACE>
        ...
        </QA>

        All generated <QA> blocks MUST be wrapped within a single <SET> tag.

        Example output:
        <SET>
            <QA>
                <Q>How does the system handle transaction limits for unverified users?</Q>
                <A>The system checks the user's verification status; if 'unverified', it enforces a maximum limit of 1000 units per transaction.</A>
                <CODE>
                if user.status == "unverified" and amount > 1000:
                    raise LimitExceededError("Unverified limit is 1000")
                </CODE>
                <TRACE>Compliance Rule: Prevent high-value fraud -> Check 'unverified' status -> Conditional amount validation</TRACE>
            </QA>
        ...
        </SET>"""

        # Setting 2: Code architecture design and solution generation prompt
        self.design_prompt = """Your task is to generate 3 new requirements and their design solutions 
        for the code component based on the provided analysis and code context.

        The response MUST include:
        1. [New Requirement]: A clear statement of the new business or technical requirement.
        2. [Design Method]: How the new requirement fits into the current class/method structure and Step-by-step technical approach.
        3. [Reasoning Trace]: Why this design is chosen based on the existing context (e.g., following specific patterns or reusing existing components).
        4. [Pseudo-code/Structure]: Proposed code structure or interface changes.

        Output Format:
        Each design pair must strictly follow this format:
        <DESIGNSET>
                <DESIGN>
                    <R>New requirement.</R>
                    <S>Solution: Detailed explanation of the design solution.</S>
                    <CODE>Code Snippet: The proposed interface or logic change.</CODE>
                    <TRACE>Reasoning Trace: Business Requirement -> Logic Design -> Code Implementation.</TRACE>
                </DESIGN>
        ...
        </DESIGNSET>


        All generated <DESIGN> blocks MUST be wrapped within a single <SET> tag.

        Example output:
        <SET>
            <DESIGN>
                <R>Implement asynchronous audit logging for transaction compliance</R>
                <S>Refactor the validation method to emit a 'ValidationCompleted' event to a message broker, allowing the audit service to consume it without blocking the main transaction flow.</S>
                <CODE>
                # New Interface:
                def validate_with_audit(data):
                    result = self.core_validator.check(data)
                    self.event_bus.publish("audit_topic", {"payload": data, "result": result})
                    return result
                </CODE>
                <TRACE>Architectural Goal: Decouple audit from transaction -> Event-driven design -> Asynchronous publisher implementation</TRACE>
            </DESIGN>
        ...
        </SET>
        """
    def get_task_prompt(self, task_type: Literal["qa", "design"]) -> str:
        """Select the appropriate prompt based on the task type."""
        if task_type == "qa":
            return self.qa_prompt
        return self.design_prompt
    def process(
        self,
        focal_component: str,
        context: str,
        task: Literal["qa", "design"] = "qa"
    ) -> str:
        """
        Processes the context and focal component to generate either QA pairs or Design Schemes.
        
        Args:
            focal_component: The specific requirement or code analysis (e.g., <ANALYSIS>...</ANALYSIS>)
            context: The full context including <INTERNAL_INFO> and <EXTERNAL_RETRIEVAL_INFO>
            task_type: 'qa' for Question-Answering pairs, 'design' for architectural design
            
        Returns:
            str: Generated high-quality content extracted from XML tags
        """
        
        # 构建任务描述
        task_description = f"""
        ### SYSTEM INSTRUCTION
        {self.get_task_prompt(task)}

        ### AVAILABLE CONTEXT (Analysis & Codebase)
        {context}

        ### FOCAL COMPONENT
        <FOCAL_INPUT>
        {focal_component}
        </FOCAL_INPUT>

        ### CONSTRAINTS
        1. Ensure the output is strictly within <SET> and </SET> tags.
        2. Base all reasoning on the provided <CONTEXT>.
        3. For QA: Focus on 'Reasoning Process' and 'Code Snippet'.
        4. For Design: Focus on 'Reasoning Trace' and consistency with existing architecture.
        """
        
        self.clear_memory() # 清除历史，确保本次任务的独立性
        self.add_to_memory("system", "You are a skilled software engineer and architect.")
        self.add_to_memory("user", task_description)
        
        # 调用大模型生成响应
        full_response = strip_think_blocks(self.generate_response())
        
        # 提取并返回
        # return self.extract_content(full_response)
        return full_response