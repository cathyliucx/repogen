from typing import Dict, Set, List, Optional
from colorama import Fore, Back, Style, init
import sys
import time

class StatusVisualizer:
    """Visualizes the workflow status of DocAssist agents in the terminal."""
    
    def __init__(self, agents: Optional[List[str]] = None):
        """Initialize the status visualizer.

        Args:
            agents: Ordered list of agent names to render. Defaults to the
                legacy set ['reader', 'searcher', 'writer', 'verifier'].
        """
        init()  # Initialize colorama
        self.active_agent = None  # Track only the currently active agent
        self.agents = agents if agents is not None else ["reader", "searcher", "writer", "verifier"]
        self._agent_art = {
            'reader': [
                "┌─────────┐",
                "│ READER  │",
                "└─────────┘"
            ],
            'searcher': [
                "┌─────────┐",
                "│SEARCHER │",
                "└─────────┘"
            ],
            'writer': [
                "┌─────────┐",
                "│ WRITER  │",
                "└─────────┘"
            ],
            'verifier': [
                "┌─────────┐",
                "│VERIFIER │",
                "└─────────┘"
            ]
        }
        self._status_message = ""
        self._current_component = ""
        self._current_file = ""
    
    def _clear_screen(self):
        """Clear the terminal screen."""
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
    
    def _get_agent_color(self, agent: str) -> str:
        """Get the color for an agent based on its state."""
        return Fore.GREEN if agent == self.active_agent else Fore.WHITE
    
    def set_current_component(self, focal_component: str, file_path: str):
        """Set the current component being processed and display its information.
        
        Args:
            focal_component: Display label for the component being processed
            file_path: Relative path to the file containing the component
        """
        self._current_component = str(focal_component) if focal_component else "unknown"
        
        self._current_file = file_path
        self._display_component_info()
    
    def _display_component_info(self):
        """Display information about the current component being processed."""
        # print(f"\n{Fore.CYAN}Currently Processing:{Style.RESET_ALL}")
        print(f"Component: {self._current_component}")
        print(f"File: {self._current_file}\n")
    
    def update(self, active_agent: str, status_message: str = ""):
        """Update the visualization with the current active agent and status.
        
        Args:
            active_agent: Name of the currently active agent
            status_message: Current status message to display
        """
        self.active_agent = active_agent  # Update the single active agent
        self._status_message = status_message
        self._clear_screen()
        
        # Build the visualization
        lines = []
        
        # Add header
        # lines.append(f"{Fore.CYAN}DocAssist Workflow Status{Style.RESET_ALL}")
        # lines.append("")
        
        # Display current component info if available
        if self._current_component and self._current_file:
            lines.append(f"Processing: {self._current_component}")
            lines.append(f"File: {self._current_file}")
            lines.append("")
        
        # Input arrow to Reader
        # lines.append("     Input")
        # lines.append("       ↓")
        
        # First row: Reader and Searcher with loop (if both are enabled)
        if 'reader' in self.agents and 'searcher' in self.agents:
            for i in range(3):
                line = (f"{self._get_agent_color('reader')}{self._agent_art['reader'][i]}"
                       f"  ←→  "
                       f"{self._get_agent_color('searcher')}{self._agent_art['searcher'][i]}"
                       f"{Style.RESET_ALL}")
                lines.append(line)
        else:
            # Fallback: render enabled agents individually in order
            for agent in self.agents:
                if agent in ('writer', 'verifier'):
                    continue
                if agent not in self._agent_art:
                    continue
                for i in range(3):
                    lines.append(f"{self._get_agent_color(agent)}{self._agent_art[agent][i]}{Style.RESET_ALL}")
        
        # Arrow from Reader to Writer
        # lines.append("       ↓")
        
        # Second row: Writer (if enabled)
        if 'writer' in self.agents:
            for i in range(3):
                line = (f"    {self._get_agent_color('writer')}{self._agent_art['writer'][i]}{Style.RESET_ALL}")
                lines.append(line)
        
        # Arrow from Writer to Verifier
        # lines.append("       ↓")
        
        # Third row: Verifier with output (if enabled)
        if 'verifier' in self.agents:
            for i in range(3):
                if i == 1:
                    line = (f"    {self._get_agent_color('verifier')}{self._agent_art['verifier'][i]}{Style.RESET_ALL}  →  Output")
                else:
                    line = (f"    {self._get_agent_color('verifier')}{self._agent_art['verifier'][i]}{Style.RESET_ALL}")
                lines.append(line)
        
        # # Feedback arrows from Verifier
        # lines.append("       ↑")
        # lines.append("    ↗  ↑")
        
        # Add status message
        if self._status_message:
            lines.append("")
            comp = self._current_component or "unknown"
            lines.append(f"{Fore.YELLOW}Status: {self._status_message} [{comp}]{Style.RESET_ALL}")
        
        # Print the visualization
        print("\n".join(lines))
        sys.stdout.flush()
    
    def reset(self):
        """Reset the visualization state."""
        self.active_agent = None
        self._status_message = ""
        self._current_component = ""
        self._current_file = ""
        self._clear_screen() 