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
import logging
import re
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
    },
    "gap_analysis": {
        "name": "Gap Analysis",
        "filename": "gap_analysis.md",
        "description": "Analysis of drift between codebase and design documents",
        "template": """# Gap Analysis

## Overview
This document highlights the discrepancies between the current programmatic state of the codebase and the expected architecture defined in the design documents.

## Identified Discrepancies
- [Code feature X] exists but is not in the [Y] design document.

## Resolution Plan
- Action items
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
        
        log = logging.getLogger(__name__)
        doc_path = self.get_doc_path(doc_type)
        lines = current_content.split('\n')

        def _normalize_heading(text: str) -> str:
            # Normalize markdown heading text for exact, resilient matching.
            normalized = text.strip().lower()
            normalized = re.sub(r'[*_`]+', '', normalized)
            # Treat "1. Frontend" and "Frontend" as the same section name.
            normalized = re.sub(r'^\d+\.\s*', '', normalized)
            normalized = re.sub(r'\s+', ' ', normalized)
            return normalized

        target_heading = _normalize_heading(section)
        heading_re = re.compile(r'^\s{0,3}(#{1,6})\s+(.*?)\s*$')
        numbered_section_re = re.compile(r'^\s*(\d+)\.\s+(.*?)\s*$')

        start_idx = -1
        start_level = 0
        matched_heading_raw = ""
        matched_mode = ""
        candidate_headings: list[str] = []
        matches: list[dict[str, int | str]] = []  # {idx, mode, level, raw}

        for idx, line in enumerate(lines):
            m = heading_re.match(line)
            if m:
                level = len(m.group(1))
                heading_text_raw = m.group(2).strip()
                heading_text = _normalize_heading(heading_text_raw)
                candidate_headings.append(heading_text_raw)
                if heading_text == target_heading:
                    matches.append({"idx": idx, "mode": "markdown", "level": level, "raw": heading_text_raw})

            n = numbered_section_re.match(line)
            if n:
                heading_text_raw = n.group(2).strip()
                heading_text = _normalize_heading(heading_text_raw)
                candidate_headings.append(heading_text_raw)
                if heading_text == target_heading:
                    matches.append({"idx": idx, "mode": "numbered", "level": 0, "raw": heading_text_raw})

        # Prefer the earliest matching section in the document.
        if matches:
            matches.sort(key=lambda m: int(m["idx"]))
            first = matches[0]
            start_idx = int(first["idx"])
            start_level = int(first["level"])
            matched_heading_raw = str(first["raw"])
            matched_mode = str(first["mode"])

        def _section_end_idx(lines_: list[str], section_start: int, mode: str, level: int) -> int:
            end = len(lines_)
            if mode == "numbered":
                for idx in range(section_start + 1, len(lines_)):
                    if numbered_section_re.match(lines_[idx]):
                        end = idx
                        break
            else:
                for idx in range(section_start + 1, len(lines_)):
                    m = heading_re.match(lines_[idx])
                    if m and len(m.group(1)) <= level:
                        end = idx
                        break
            return end

        before_len = len(current_content)
        if start_idx >= 0:
            # Remove duplicate sections with the same normalized name, keeping the first one.
            duplicate_ranges: list[tuple[int, int]] = []
            for m in matches[1:]:
                dup_start = int(m["idx"])
                dup_mode = str(m["mode"])
                dup_level = int(m["level"])
                dup_end = _section_end_idx(lines, dup_start, dup_mode, dup_level)
                duplicate_ranges.append((dup_start, dup_end))

            for dup_start, dup_end in sorted(duplicate_ranges, key=lambda r: r[0], reverse=True):
                del lines[dup_start:dup_end]

            end_idx = _section_end_idx(lines, start_idx, matched_mode, start_level)

            replacement = [lines[start_idx], content]
            new_lines = lines[:start_idx] + replacement + lines[end_idx:]
            log.info(
                "[DesignDocumentManager.update_section] doc=%s path=%s section=%r matched_heading=%r mode=%s level=%s replace_range=[%s,%s) removed_duplicates=%d",
                doc_type, doc_path, section, matched_heading_raw, matched_mode, start_level, start_idx, end_idx, len(duplicate_ranges),
            )
        else:
            # If exact heading wasn't found, append a new section.
            new_lines = list(lines)
            if new_lines and new_lines[-1].strip() != "":
                new_lines.append("")
            new_lines.append(f"## {section}")
            new_lines.append(content)
            log.warning(
                "[DesignDocumentManager.update_section] doc=%s path=%s section=%r heading_not_found; appended_new_section. candidates=%s",
                doc_type, doc_path, section, candidate_headings[:20],
            )

        updated_content = '\n'.join(new_lines)
        after_len = len(updated_content)
        if before_len == after_len and current_content == updated_content:
            log.warning(
                "[DesignDocumentManager.update_section] doc=%s path=%s section=%r no_content_change",
                doc_type, doc_path, section,
            )
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
