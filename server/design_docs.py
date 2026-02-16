"""
Design Document Management System for Plan Mode

Manages design documents that are created during planning phase:
- Functionalities (feature definitions)
- Tech Stack (technology choices)
- Database Design (schema, models)
- User Flow Design (UX journeys)
- Architecture (system design)
- API Design (endpoints, contracts)
- Requirements (business requirements)

Documents are stored as markdown files in the session workspace.
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

# Design document types
DESIGN_DOC_TYPES = {
    "functionalities": {
        "name": "Functionalities",
        "filename": "functionalities.md",
        "description": "Feature list and functional requirements",
        "template": """# Functionalities

## Overview
[Brief description of the system/application]

## Core Features
1. **Feature Name**
   - Description: 
   - User Story: As a [user type], I want [goal] so that [benefit]
   - Acceptance Criteria:
     - [ ] Criterion 1
     - [ ] Criterion 2

## Future Enhancements
- Enhancement ideas for future versions

## Notes
- Additional considerations
"""
    },
    "tech_stack": {
        "name": "Tech Stack",
        "filename": "tech_stack.md",
        "description": "Technology choices and justifications",
        "template": """# Tech Stack

## Frontend
- **Framework**: 
- **UI Library**: 
- **State Management**: 
- **Build Tool**: 

## Backend
- **Language**: 
- **Framework**: 
- **API Type**: 

## Database
- **Type**: 
- **ORM/Query Builder**: 

## Infrastructure
- **Hosting**: 
- **CI/CD**: 
- **Monitoring**: 

## Development Tools
- **Version Control**: 
- **Package Manager**: 
- **Testing**: 

## Justifications
[Explain key technology choices]

## Alternatives Considered
[Document alternatives and why they were not chosen]
"""
    },
    "database_design": {
        "name": "Database Design",
        "filename": "database_design.md",
        "description": "Data models, schema, and relationships",
        "template": """# Database Design

## Entities

### Entity Name
```
- field_name: type (constraints)
- created_at: timestamp
- updated_at: timestamp
```

## Relationships
- Entity1 → Entity2 (relationship type)

## Indexes
- Table.field (reason)

## Migrations Strategy
[How to handle schema changes]

## Data Flow
[How data moves through the system]

## Considerations
- Scaling strategy
- Backup/recovery
- Data retention policies
"""
    },
    "user_flow": {
        "name": "User Flow Design",
        "filename": "user_flow.md",
        "description": "User journeys and interaction patterns",
        "template": """# User Flow Design

## Primary User Personas
1. **Persona Name**
   - Role: 
   - Goals: 
   - Pain Points: 

## User Journeys

### Journey Name
1. Entry Point: [How user arrives]
2. Steps:
   - Step 1: [Action] → [Result]
   - Step 2: [Action] → [Result]
3. Success Criteria: [What defines success]
4. Edge Cases: [Alternative paths]

## UI/UX Considerations
- Navigation structure
- Key interactions
- Responsive design requirements
- Accessibility requirements

## Wireframes / Mockups
[Links or descriptions of visual designs]
"""
    },
    "architecture": {
        "name": "Architecture",
        "filename": "architecture.md",
        "description": "System architecture and component design",
        "template": """# Architecture

## System Overview
[High-level description of the system]

## Components

### Component Name
- **Purpose**: 
- **Responsibilities**: 
- **Dependencies**: 
- **Interfaces**: 

## Architecture Patterns
- Pattern used (e.g., MVC, Microservices, Event-Driven)
- Rationale: 

## Data Flow
```
[Component A] → [Component B] → [Component C]
```

## Deployment Architecture
- Development environment
- Staging environment
- Production environment

## Scalability Considerations
- Horizontal vs vertical scaling
- Caching strategy
- Load balancing

## Security Considerations
- Authentication/Authorization
- Data encryption
- API security

## Performance Considerations
- Expected load
- Response time targets
- Optimization strategies
"""
    },
    "api_design": {
        "name": "API Design",
        "filename": "api_design.md",
        "description": "API endpoints, request/response formats",
        "template": """# API Design

## Base URL
```
Development: http://localhost:PORT
Production: https://api.example.com
```

## Authentication
- Method: [Bearer Token / OAuth / API Key]
- Headers: 

## Endpoints

### Endpoint Name
```
METHOD /path/:param
```

**Description**: 

**Request**:
```json
{
  "field": "value"
}
```

**Response** (200):
```json
{
  "data": {},
  "message": "Success"
}
```

**Errors**:
- 400: Bad Request
- 401: Unauthorized
- 404: Not Found
- 500: Server Error

## Rate Limiting
- Limits per endpoint
- Rate limit headers

## Versioning Strategy
- How API versions are managed

## Webhooks
- Available webhook events
- Payload formats
"""
    },
    "requirements": {
        "name": "Requirements",
        "filename": "requirements.md",
        "description": "Business and technical requirements",
        "template": """# Requirements

## Business Requirements
1. **Requirement Name**
   - Description: 
   - Priority: High / Medium / Low
   - Stakeholder: 

## Technical Requirements
- Performance requirements
- Scalability requirements
- Security requirements
- Compliance requirements

## Functional Requirements
[Detailed functional requirements from business perspective]

## Non-Functional Requirements
- Availability: 
- Response Time: 
- Throughput: 
- Data Retention: 

## Constraints
- Budget constraints
- Timeline constraints
- Technology constraints
- Resource constraints

## Assumptions
- Key assumptions made during planning

## Dependencies
- External system dependencies
- Third-party service dependencies

## Success Metrics
- How success will be measured
- KPIs to track
"""
    }
}


class DesignDocumentManager:
    """Manages design documents for a session."""
    
    def __init__(self, workspace_root: str):
        """
        Initialize design document manager for a workspace.
        
        Args:
            workspace_root: Root directory of the session workspace
        """
        self.workspace_root = Path(workspace_root)
        self.design_dir = self.workspace_root / ".openscrum" / "design"
        self.design_dir.mkdir(parents=True, exist_ok=True)
    
    def get_doc_path(self, doc_type: str) -> Path:
        """Get the file path for a design document type."""
        if doc_type not in DESIGN_DOC_TYPES:
            raise ValueError(f"Unknown document type: {doc_type}. Valid types: {list(DESIGN_DOC_TYPES.keys())}")
        return self.design_dir / DESIGN_DOC_TYPES[doc_type]["filename"]
    
    def create_document(self, doc_type: str) -> str:
        """
        Create a new design document with template content.
        
        Args:
            doc_type: Type of document to create
            
        Returns:
            Path to the created document
        """
        if doc_type not in DESIGN_DOC_TYPES:
            raise ValueError(f"Unknown document type: {doc_type}")
        
        doc_path = self.get_doc_path(doc_type)
        
        # Don't overwrite existing document
        if doc_path.exists():
            return str(doc_path)
        
        # Write template
        template = DESIGN_DOC_TYPES[doc_type]["template"]
        doc_path.write_text(template, encoding="utf-8")
        
        return str(doc_path)
    
    def read_document(self, doc_type: str) -> Optional[str]:
        """
        Read a design document.
        
        Args:
            doc_type: Type of document to read
            
        Returns:
            Document content or None if doesn't exist
        """
        if doc_type not in DESIGN_DOC_TYPES:
            raise ValueError(f"Unknown document type: {doc_type}")
        
        doc_path = self.get_doc_path(doc_type)
        
        if not doc_path.exists():
            return None
        
        return doc_path.read_text(encoding="utf-8")
    
    def write_document(self, doc_type: str, content: str) -> str:
        """
        Write/update a design document.
        
        Args:
            doc_type: Type of document to write
            content: Content to write
            
        Returns:
            Path to the document
        """
        if doc_type not in DESIGN_DOC_TYPES:
            raise ValueError(f"Unknown document type: {doc_type}")
        
        doc_path = self.get_doc_path(doc_type)
        doc_path.write_text(content, encoding="utf-8")
        
        return str(doc_path)
    
    def update_section(self, doc_type: str, section: str, content: str) -> str:
        """
        Update a specific section of a design document.
        
        Args:
            doc_type: Type of document
            section: Section heading to update (e.g., "Frontend")
            content: New content for the section
            
        Returns:
            Updated document content
        """
        current_content = self.read_document(doc_type)
        
        if current_content is None:
            # Create new document if it doesn't exist
            self.create_document(doc_type)
            current_content = self.read_document(doc_type)
        
        # Ensure current_content is not None
        if current_content is None:
            current_content = ""
        
        # Simple section replacement (can be enhanced)
        # Look for ## Section or # Section
        lines = current_content.split('\n')
        new_lines = []
        in_section = False
        section_found = False
        
        for line in lines:
            if line.startswith('#') and section.lower() in line.lower():
                in_section = True
                section_found = True
                new_lines.append(line)
                new_lines.append(content)
            elif in_section and line.startswith('#'):
                in_section = False
                new_lines.append(line)
            elif not in_section:
                new_lines.append(line)
        
        # If section wasn't found, append it
        if not section_found:
            new_lines.append(f"\n## {section}")
            new_lines.append(content)
        
        updated_content = '\n'.join(new_lines)
        self.write_document(doc_type, updated_content)
        
        return updated_content
    
    def list_documents(self) -> Dict[str, Any]:
        """
        List all design documents and their status.
        
        Returns:
            Dictionary with document info
        """
        docs = {}
        for doc_type, info in DESIGN_DOC_TYPES.items():
            doc_path = self.get_doc_path(doc_type)
            exists = doc_path.exists()
            
            docs[doc_type] = {
                "name": info["name"],
                "filename": info["filename"],
                "description": info["description"],
                "exists": exists,
                "path": str(doc_path) if exists else None,
                "last_modified": datetime.fromtimestamp(doc_path.stat().st_mtime).isoformat() if exists else None
            }
        
        return docs
    
    def get_all_documents(self) -> Dict[str, Optional[str]]:
        """
        Get all design documents' content.
        
        Returns:
            Dictionary mapping doc_type to content (None if doesn't exist)
        """
        return {
            doc_type: self.read_document(doc_type)
            for doc_type in DESIGN_DOC_TYPES.keys()
        }
    
    def delete_document(self, doc_type: str) -> bool:
        """
        Delete a design document.
        
        Args:
            doc_type: Type of document to delete
            
        Returns:
            True if deleted, False if didn't exist
        """
        if doc_type not in DESIGN_DOC_TYPES:
            raise ValueError(f"Unknown document type: {doc_type}")
        
        doc_path = self.get_doc_path(doc_type)
        
        if doc_path.exists():
            doc_path.unlink()
            return True
        
        return False
