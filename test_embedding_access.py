#!/usr/bin/env python3
"""Test which OpenAI embedding models are accessible."""

import os
import sys
from pathlib import Path

# Load environment
try:
    from dotenv import load_dotenv
    env_path = Path.home() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from openai import OpenAI

api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    print('ERROR: OPENAI_API_KEY not found in environment or ~/.env')
    sys.exit(1)

print(f'Testing with API key: {api_key[:20]}...')
print(f'Full key length: {len(api_key)} chars')
print()

client = OpenAI(api_key=api_key)

# Test text-embedding-3-small
print('Testing text-embedding-3-small...')
try:
    response = client.embeddings.create(
        input='test',
        model='text-embedding-3-small'
    )
    print('✓ SUCCESS: text-embedding-3-small is accessible')
    print(f'  Embedding dimension: {len(response.data[0].embedding)}')
except Exception as e:
    print(f'✗ FAILED: {e}')

print()

# Test text-embedding-ada-002
print('Testing text-embedding-ada-002...')
try:
    response = client.embeddings.create(
        input='test',
        model='text-embedding-ada-002'
    )
    print('✓ SUCCESS: text-embedding-ada-002 is accessible')
    print(f'  Embedding dimension: {len(response.data[0].embedding)}')
except Exception as e:
    print(f'✗ FAILED: {e}')

print()
print('Recommendation:')
print('- If text-embedding-3-small works, set: export OPENSCRUM_MEMSEARCH_EMBEDDING_MODEL=text-embedding-3-small')
print('- If only ada-002 works, set: export OPENSCRUM_MEMSEARCH_EMBEDDING_MODEL=text-embedding-ada-002')
