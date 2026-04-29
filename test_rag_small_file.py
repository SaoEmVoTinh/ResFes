import os
import sys
from pathlib import Path

# Add app/src/main/python to sys.path so we can import resfes
sys.path.insert(0, str(Path("app/src/main/python").absolute()))

import resfes
from resfes import ingest_document_from_path, semantic_search, generate_answer, generate_answer_agentic, CHUNK_SIZE, CHUNK_OVERLAP

def main():
    print("=== DEBUG RAG FLOW FOR SMALL FILE ===")
    
    # 1. Create a small mock file
    test_file = Path("knowledge/uploads/test_small_doc.txt")
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_text = "Chiến lược số một thường liên quan đến việc xác định và ưu tiên các mục tiêu chính. Trong bối cảnh của hệ thống RAG và truy vấn thông tin, chiến lược số một có thể là xác định rõ ràng câu hỏi hoặc yêu cầu của người dùng để đảm bảo hệ thống trả về thông tin chính xác và phù hợp."
    test_file.write_text(test_text, encoding="utf-8")
    print(f"[1] Created test file: {test_file}")

    # 2. Ingest the document
    with resfes.app.app_context(): # Need app context for g.db
        res = ingest_document_from_path(test_file, original_name="test_small_doc.txt", file_type="txt", subject="test_subject")
        doc_id = res['id']
        print(f"[2] Ingested document: doc_id={doc_id}, chunks={res['chunks']}, vectors={res['vectors']}")

        # 3. Retrieve chunks
        query = "Chiến lược số một là gì?"
        print(f"\n[3] Query: {query}")
        chunks = semantic_search(query, subject="test_subject", top_k=3, expand=False)
        print(f"    Retrieved {len(chunks)} chunks:")
        for i, c in enumerate(chunks):
            print(f"    - Chunk {i+1} (score={c['score']}): {c['text']}")

        # 4. Generate answer (Standard)
        print("\n[4] Generation (Standard):")
        ans_std = generate_answer(query, chunks, subject="test_subject")
        print(f"    Answer: {ans_std}")

        # 5. Generate answer (Agentic)
        print("\n[5] Generation (Agentic):")
        ans_age = generate_answer_agentic(query, chunks, subject="test_subject")
        print(f"    Answer: {ans_age.get('answer')}")
        print(f"    Agent used: {ans_age.get('synthesis', {}).get('picked_agent')}")

if __name__ == "__main__":
    main()
