workspace "TV Character Chatbot" "RAG-grounded TV character roleplay chatbot — React + FastAPI + Supabase pgvector + Groq, with SQLite eval logging." {

    model {

        // ── People ────────────────────────────────────────────────────────────
        user = person "User" "Chats with TV characters in a web browser."

        // ── Our system ────────────────────────────────────────────────────────
        chatbot = softwareSystem "TV Character Chatbot" "Streams in-character responses grounded in real show dialogue via RAG." {

            spa = container "React SPA" "Character selection and chat UI. Served as static files from the backend." "React 18 · TypeScript 5 · Vite 5 · Tailwind CSS 3" {
                tags "Web Browser"

                cLanding  = component "Landing Page"      "Character selection grid with animated portrait cards."         "LandingPage.tsx"
                cChat     = component "Chat View"         "Full chat screen: header, scrollable message list, input bar."  "ChatView.tsx"
                cMessage  = component "Message"           "Renders user + bot bubbles. Shows TypingDots before first token, streaming cursor during generation." "Message.tsx"
                cWsHook   = component "useWebSocket"      "Manages WebSocket lifecycle with 3 s auto-reconnect."           "useWebSocket.ts"
                cChatHook = component "useChat"           "Message state + RAF-batched token flushing (1 React update / frame)." "useChat.ts"
            }

            api = container "FastAPI Server" "WebSocket server — orchestrates RAG retrieval, prompt assembly, streamed LLM responses, and async eval logging." "Python 3.13 · FastAPI · Uvicorn · server_llama.py" {

                cWs      = component "WebSocket Handler"  "Accepts set_character / chat frames. Emits token / done / error frames." "/ws endpoint"
                cRag     = component "RAG Retriever"      "Two-pass retrieval: 3 canon scenes (world knowledge) + 2 exemplars (voice anchor) via Supabase RPC." "retrieve_from_supabase()"
                cPrompt  = component "Prompt Builder"     "Assembles system prompt: roleplay contract + profile sections + RAG context + rolling 10-turn history." "stream_reply()"
                cGroq    = component "Groq Client"        "OpenAI-compatible SDK client. Sends conversation, receives SSE token stream." "openai.OpenAI → api.groq.com"
                cClean   = component "Text Cleaner"       "Strips <think>…</think>, asterisks, bracketed actions, character name prefixes. Queues words." "regex pipeline"
                cProfile = component "Profile Loader"     "Loads character_profiles.json at startup and infers each character's show. Parses IDENTITY / SPEECH / TRIGGERS / RULES sections." "load_descriptions_from_file()"
                cEval    = component "Eval Logger"        "Asynchronously records character, prompt, response, backend, and timings to SQLite for offline analysis." "eval_logger.py"
                cStatic  = component "Static File Server" "Serves the built React SPA from ./static/ with HTML fallback for client-side routing." "FastAPI StaticFiles"
            }

            profiles = container "Character Profiles" "LLM-synthesised character persona definitions committed to the repo." "character_profiles.json"
            evalLogs = container "Evaluation Log Store" "SQLite database used to log chat turns and timing metrics for evaluation." "SQLite · ./eval_logs.db"
        }

        // ── External systems ──────────────────────────────────────────────────
        groq = softwareSystem "Groq Cloud" "Hosted LLM inference on custom LPU hardware. Model: llama-3.3-70b-versatile." {
            tags "External"
        }

        supabase = softwareSystem "Supabase" "Managed PostgreSQL with pgvector extension. Stores 384-dim scene embeddings with HNSW index." {
            tags "External"
        }

        // ── Relationships — container level ───────────────────────────────────
        user    -> spa      "Opens app, selects character, types messages"   "HTTPS"
        spa     -> api      "Chat and control frames"                        "WebSocket / WSS"
        api     -> groq     "chat/completions (streaming)"                   "HTTPS · SSE"
        api     -> supabase "match_tv_scenes() RPC"                         "HTTPS · supabase-py 2.28"
        api     -> profiles "Reads character personas at startup"
        api     -> evalLogs "Writes chat turns and timing metrics" "SQLite"

        // ── Relationships — component level ───────────────────────────────────
        cWsHook   -> cWs      "Connects and forwards JSON frames"
        cChatHook -> cWsHook  "send() / onmessage callback"

        cWs      -> cRag     "Triggers two-pass retrieval per user message"
        cWs      -> cPrompt  "Requests assembled system prompt"
        cWs      -> cGroq    "Sends full conversation to LLM"
        cWs      -> cClean   "Pipes raw token stream through cleaner"
        cWs      -> cEval    "Logs completed responses asynchronously"
        cPrompt  -> cRag     "Injects 3 canon scenes + 2 voice exemplars"
        cPrompt  -> cProfile "Reads character identity, speech style, rules"
        cRag     -> supabase "Similarity search — filter: show + doc_type + has_<character>"
        cGroq    -> groq     "Streaming LLM call — llama-3.3-70b-versatile"

        // ── Deployment model — Render production ────────────────────────────
        deploymentEnvironment "production" {

            deploymentNode "User's Browser" "" "" {
                containerInstance spa
            }

            deploymentNode "Render.com" "" "" {
                infrastructureNode "static/" ""
                containerInstance api
                containerInstance profiles
                containerInstance evalLogs
            }

            deploymentNode "Groq Cloud" "" "" {
                softwareSystemInstance groq
            }

            deploymentNode "Supabase Cloud" "" "" {
                softwareSystemInstance supabase
            }
        }
    }

    views {

        // ── Level 1 — System Context ──────────────────────────────────────────
        systemContext chatbot "L1_Context" "Level 1 — System Context: who uses the chatbot and which external systems it depends on." {
            include *
            autoLayout lr 400 220
        }

        // ── Level 2 — Containers ──────────────────────────────────────────────
        container chatbot "L2_Containers" "Level 2 — Containers: the deployable units and data stores." {
            include *
            autoLayout lr 420 240
        }

        // ── Level 3 — Backend components ─────────────────────────────────────
        component api "L3_Backend" "Level 3 — Backend Components: internal structure of the FastAPI server." {
            include *
            autoLayout lr 520 260
        }

        // ── Level 3 — Frontend components ────────────────────────────────────
        component spa "L3_Frontend" "Level 3 — Frontend Components: React SPA structure." {
            include *
            autoLayout lr 420 220
        }

        // ── Deployment — Render ───────────────────────────────────────────────
        deployment chatbot production "D1_Render" "Deployment on Render.com (single web service)." {
            include *
        }

        // ── Styles ────────────────────────────────────────────────────────────
        styles {

            element "Person" {
                shape      Person
                background #1e3a5f
                color      #e2e8f0
                stroke     #38bdf8
                fontSize   14
            }

            element "Software System" {
                background #1e293b
                color      #e2e8f0
                stroke     #334155
            }

            element "External" {
                background #0f172a
                color      #94a3b8
                stroke     #1e293b
            }

            element "Container" {
                background #162032
                color      #e2e8f0
                stroke     #38bdf8
            }

            element "Component" {
                background #0d1b2a
                color      #cbd5e1
                stroke     #1e3a5f
            }

            element "Web Browser" {
                shape WebBrowser
            }

            element "Infrastructure Node" {
                background #1a2744
                color      #94a3b8
                stroke     #334155
            }

            relationship "Relationship" {
                color     #e2e8f0
                thickness 2
            }
        }

        theme default
    }
}
