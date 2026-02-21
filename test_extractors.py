import asyncio
from server.session.session import get_session
from server.tools.context import set_tool_context
from server.tools.system_tools import extract_api_routes, extract_db_schemas, list_components, list_services, scan_codebase

async def test_extractors():
    session_id = "ses_000000e5a70e266axrwmJasbwY"
    session_svc = get_session()
    session = session_svc.get(session_id)
    if not session:
        print("Session not found")
        return
        
    set_tool_context(session_id, session)
    
    print("--- SCAN CODEBASE ---")
    print(scan_codebase())
    
    print("\n--- EXTRACT API ROUTES ---")
    print(extract_api_routes())
    
    print("\n--- EXTRACT DB SCHEMAS ---")
    print(extract_db_schemas())
    
    print("\n--- LIST COMPONENTS ---")
    print(list_components())
    
    print("\n--- LIST SERVICES ---")
    print(list_services())

if __name__ == "__main__":
    asyncio.run(test_extractors())
