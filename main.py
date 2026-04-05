"""
Consciousness-First Dual-Pass Agent Architecture — Main Orchestrator
  Layer 1: Dreamer (Consciousness) → free text, temp=0.7
  Layer 2: Executor (Translator) → JSON, temp=0.1
  Layer 3: Python Orchestrator → security, execution, synchronization
"""
import sys
import re
from pathlib import Path

from core.llm import consciousness_call, is_alive
from core.memory import Memory, EntityTracker, trim_history
from core.auto_dream import perform_startup_dreaming
from tools.bash import bash
from tools.read_file_tool import read_file, list_code_outline
from tools.write_file_tool import write_file, edit_file
from tools.memory_tools import append_to_memory, update_section, read_section, edit_line, delete_line
from tools.app_launcher import (
    open_app, open_app_workspace, youtube_search_play, switch_workspace,
    read_active_workspace, list_open_windows, move_window_workspace, vscode_open_project,
)
from tools.tavily_tools import web_research, read_page
from tools.obsidian_tools import (
    retrieve_relevant_context,
    search_vault,
    read_note,
    write_to_obsidian,
    append_to_note,
    update_frontmatter,
    search_by_tag,
    read_frontmatter_only,
    get_backlinks,
    get_outgoing_links,
    move_note,
    open_in_obsidian,
    log_reflection_failure,
    log_reflection_correction,
    ReflectionFailure,
)
from core.audio_handler import speak, listen

from config import (
    BASE_MAX_LOOPS,
    EXTENDED_MAX_LOOPS,
    ASSISTANT_NAME,
    USER_NAME,
    OBSIDIAN_RAG_TOP_K,
)
from prompts import SYSTEM_GREETING


def load_system() -> str:
    """Loads SOUL.md + USER.md + WISDOM.md + Neural Graph as the system prompt."""
    from config import OBSIDIAN_VAULT_DIR, VAULT_DIR_MEMORY, VAULT_DIR_NEURAL_GRAPH
    vault_path = Path(OBSIDIAN_VAULT_DIR).expanduser().resolve()
    
    # V2 path with legacy fallback
    memory_dir = vault_path / VAULT_DIR_MEMORY
    if not memory_dir.exists():
        legacy = vault_path / "_Memory"
        if legacy.exists():
            memory_dir = legacy
    
    base_dir = Path(__file__).parent
    parts = []

    for fname in ["SOUL.md", "SKILL.md", "USER.md", "WISDOM.md", "OBSIDIAN_RULES.md"]:
        p = memory_dir / fname
        if not p.exists():
            p_fallback = base_dir / fname
            if p_fallback.exists():
                p = p_fallback
                
        if p.exists():
            parts.append(p.read_text(encoding="utf-8"))
            print(f"[SYSTEM] {fname} loaded successfully! (Length: {len(parts[-1])} characters)")
        else:
            if fname != "OBSIDIAN_RULES.md":
                print(f"[WARNING] {fname} not found! Searched at: {p}")

    # V2: Load Neural Graph Summary (if available)
    graph_summary = vault_path / VAULT_DIR_NEURAL_GRAPH / "summary.md"
    if graph_summary.exists():
        graph_text = graph_summary.read_text(encoding="utf-8")
        parts.append(f"<neural_graph_summary>\n{graph_text}\n</neural_graph_summary>")
        print(f"[SYSTEM] Neural Graph loaded! ({graph_summary.stat().st_size} bytes)")

    return "\n\n---\n\n".join(parts)


def _extract_requested_workspace(text: str) -> str | None:
    t = text.lower()
    patterns = [
        r"workspace\s*(\d+)",
        r"(\d+)\s*\.?\s*workspace",
    ]
    for p in patterns:
        m = re.search(p, t)
        if not m:
            continue
        raw = m.group(1)
        if not raw.isdigit():
            continue
        n = int(raw)
        if n == 0:
            return "10"
        if 1 <= n <= 10:
            return str(n)
    return None



def execute_tool(action: dict) -> str:
    """
    Executes JSON command from Executor through security filter.
    Returns result as plain text.
    """
    action_name = action.get("action", "none")

    try:
        if action_name == "bash":
            command = action.get("command", "")
            print(f"  └─> Command: {command}")
            return bash(command)

        elif action_name == "read_file":
            file = action.get("file", "")
            start = int(action.get("start_line", 1))
            end = int(action.get("end_line", 200))
            print(f"  └─> File: {file} (Lines {start}-{end})")
            return read_file(file, start, end)

        elif action_name == "list_code_outline":
            file = action.get("file", "")
            print(f"  └─> AST Outline: {file}")
            return list_code_outline(file)

        elif action_name == "write_file":
            file = action.get("file", "")
            content = action.get("content", "")
            print(f"  └─> File: {file}")
            return write_file(file, content)

        elif action_name == "edit_file":
            file = action.get("file", "")
            old_str = action.get("old_string", "")
            new_str = action.get("new_string", "")
            print(f"  └─> Edit File: {file} (Patching substring)")
            return edit_file(file, old_str, new_str)

        elif action_name == "memory_append":
            file = action.get("file", "")
            section = action.get("section", "")
            content = action.get("content", "")
            print(f"  └─> File: {file} | Section: {section}")
            return append_to_memory(file, section, content)

        elif action_name == "memory_update":
            file = action.get("file", "")
            section = action.get("section", "")
            new_content = action.get("new_content", "")
            print(f"  └─> File: {file} | Section: {section}")
            return update_section(file, section, new_content)

        elif action_name == "memory_read":
            file = action.get("file", "")
            section = action.get("section", "")
            print(f"  └─> File: {file} | Section to read: {section}")
            return read_section(file, section)

        elif action_name == "memory_edit":
            file = action.get("file", "")
            section = action.get("section", "")
            old_text = action.get("old", "")
            new_text = action.get("new", "")
            print(f"  └─> File: {file} | Section: {section} | '{old_text}' → '{new_text}'")
            return edit_line(file, section, old_text, new_text)

        elif action_name == "memory_delete":
            file = action.get("file", "")
            section = action.get("section", "")
            text_to_delete = action.get("to_delete", "")
            print(f"  └─> File: {file} | Section: {section} | To delete: '{text_to_delete}'")
            return delete_line(file, section, text_to_delete)

        elif action_name == "open_app":
            app = action.get("app", "")
            print(f"  └─> Application: {app}")
            return open_app(app)

        elif action_name == "vscode_open_project":
            project_path = action.get("project_path", "")
            print(f"  └─> VS Code Open Project: {project_path}")
            return vscode_open_project(project_path)

        elif action_name == "switch_workspace":
            workspace_no = action.get("workspace_no", "")
            print(f"  └─> Workspace Switch: {workspace_no}")
            return switch_workspace(workspace_no)

        elif action_name == "open_app_workspace":
            app = action.get("app", "")
            workspace_no = action.get("workspace_no", "")
            print(f"  └─> Open App in Workspace: {app} @ {workspace_no}")
            return open_app_workspace(app, workspace_no)

        elif action_name == "read_active_workspace":
            print("  └─> Read Active Workspace")
            return read_active_workspace()

        elif action_name == "list_open_windows":
            print("  └─> List Open Windows")
            return list_open_windows()

        elif action_name == "move_window_workspace":
            window = action.get("window", "")
            workspace_no = action.get("workspace_no", "")
            print(f"  └─> Move Window: {window} -> Workspace {workspace_no}")
            return move_window_workspace(window, workspace_no)

        elif action_name == "youtube_search_play":
            search_query = action.get("search_query", "")
            print(f"  └─> YouTube Search: {search_query}")
            return youtube_search_play(search_query)

        elif action_name == "web_research":
            query = action.get("query", "")
            depth = action.get("depth", "advanced")
            print(f"  └─> Web Research: {query} | Depth: {depth}")
            return web_research(query, depth)

        elif action_name == "read_page":
            url = action.get("url", "")
            print(f"  └─> Read Page: {url}")
            return read_page(url)

        elif action_name == "deep_research":
            query = action.get("query", "")
            print(f"  └─> Deep Research: {query}")
            from tools.tavily_tools import deep_research
            return deep_research(query)

        elif action_name == "crawl_page":
            url = action.get("url", "")
            print(f"  └─> Crawl Page: {url}")
            from tools.tavily_tools import crawl_page
            return crawl_page(url)

        elif action_name == "search_vault":
            query = action.get("query", "")
            print(f"  └─> Vault Search: {query}")
            return search_vault(query)

        elif action_name == "read_note":
            filename = action.get("filename", "")
            print(f"  └─> Read Note: {filename}")
            return read_note(filename)

        elif action_name == "write_to_obsidian":
            title = action.get("title", "")
            content = action.get("content", "")
            folder = action.get("folder", "") or "correction_logs"
            print(f"  └─> Write Obsidian Note: {title} @ {folder}")
            return write_to_obsidian(title=title, content=content, folder=folder)

        elif action_name == "append_to_note":
            filename = action.get("filename", "")
            content = action.get("content", "")
            print(f"  └─> Append Note: {filename}")
            return append_to_note(filename=filename, content=content)

        elif action_name == "update_frontmatter":
            filename = action.get("filename", "")
            key = action.get("key", "")
            value = action.get("value", "")
            print(f"  └─> Update Frontmatter: {filename} | {key}={value}")
            return update_frontmatter(filename=filename, key=key, value=value)

        elif action_name == "search_by_tag":
            tag = action.get("tag", "")
            print(f"  └─> Search By Tag: {tag}")
            return search_by_tag(tag=tag)

        elif action_name == "read_frontmatter_only":
            filename = action.get("filename", "")
            print(f"  └─> Read Frontmatter Only: {filename}")
            return read_frontmatter_only(filename=filename)

        elif action_name == "get_backlinks":
            filename = action.get("filename", "")
            print(f"  └─> Get Backlinks: {filename}")
            return get_backlinks(filename=filename)

        elif action_name == "get_outgoing_links":
            filename = action.get("filename", "")
            print(f"  └─> Get Outgoing Links: {filename}")
            return get_outgoing_links(filename=filename)

        elif action_name == "move_note":
            filename = action.get("filename", "")
            new_folder = action.get("new_folder", "")
            print(f"  └─> Move Note: {filename} -> {new_folder}")
            return move_note(filename=filename, new_folder=new_folder)

        elif action_name == "open_in_obsidian":
            filename = action.get("filename", "")
            print(f"  └─> Open In Obsidian: {filename}")
            return open_in_obsidian(filename=filename)

        else:
            return f"❌ Invalid action: {action_name}"

    except Exception as e:
        return f"❌ Tool execution error: {type(e).__name__}: {e}"


SYSTEM = load_system()



def main():
    if not is_alive():
        print("❌ Ollama is not running. Start: ollama serve")
        sys.exit(1)

    print(f"{SYSTEM_GREETING}")
    print('   Type "exit" to quit\n')

    # Run auto_dream startup hook
    perform_startup_dreaming()

    memory = Memory()
    tracker = EntityTracker()
    history = []
    last_failure: ReflectionFailure | None = None

    while True:
        # Either read from mic or input()
        use_mic = False
        try:
            print()
            raw_input = input(f"╭─ {USER_NAME}\n╰─❯ ").strip()
            if raw_input.lower() in ('/mic', 'mic'):
                use_mic = True
                user = listen()
                if not user:
                    print("Could not hear you. Please type or try again.")
                    continue
            else:
                user = raw_input
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if not user:
            continue
        if user.lower() in ("exit", "q"):
            print("Goodbye.")
            break

        if last_failure:
            correction_markers = [
                "doğrusu", "yanlış", "hata", "instead", "correct", "fix", "should be", "olmali", "olmalı"
            ]
            lower_user = user.lower()
            if any(marker in lower_user for marker in correction_markers):
                correction_result = log_reflection_correction(
                    last_failure,
                    f"User correction feedback: {user}",
                )
                print(f"[Reflection] {correction_result}")
                last_failure = None

        past = memory.recall(user)
        system = SYSTEM
        if past:
            system += f"\n\n<past_memory>\nThe following is past context recalled from memory:\n{past}\n</past_memory>"

        obsidian_context = retrieve_relevant_context(user, top_k=OBSIDIAN_RAG_TOP_K)
        if obsidian_context and not obsidian_context.startswith("⚠️"):
            system += (
                "\n\n<obsidian_rag_context>\n"
                "Before acting, use this relevant knowledge from your notes:\n"
                f"{obsidian_context}\n"
                "</obsidian_rag_context>"
            )

        history.append({"role": "user", "content": user})
        print()

        max_loops = BASE_MAX_LOOPS
        error_count = 0
        loop = 0
        executed_actions = set() 

        while loop < max_loops:
            step_label = f"{'='*20} [Loop {loop+1}/{max_loops}] {'='*20}"
            print(f"\n{step_label}")

            consciousness, actions = consciousness_call(history, system=system)

            requested_workspace = _extract_requested_workspace(user)
            if requested_workspace:
                guarded_actions = []
                for a in actions:
                    action = a.get("action", "none")
                    guarded = dict(a)

                    if action == "open_app":
                        guarded["action"] = "open_app_workspace"
                        guarded["workspace_no"] = requested_workspace
                    elif action in {"open_app_workspace", "switch_workspace", "move_window_workspace"}:
                        current = str(guarded.get("workspace_no", "")).strip()
                        if current != requested_workspace:
                            print(
                                f"[Guardrail] Workspace override: {action} {current or '-'} -> {requested_workspace}"
                            )
                        guarded["workspace_no"] = requested_workspace

                    guarded_actions.append(guarded)
                actions = guarded_actions

            if all(a.get("action", "none") == "none" for a in actions):
                print(f"\n[Executor] Action: none")
                history.append({"role": "assistant", "content": consciousness})

                saved = memory.save(user, consciousness)
                if saved:
                    print("[Saved to memory]")
                print()
                if use_mic:
                    speak(consciousness)
                
                break


            history.append({"role": "assistant", "content": consciousness})

            seen = set()
            unique_actions = []
            for a in actions:
                key = str(sorted(a.items()))
                if key not in seen:
                    seen.add(key)
                    unique_actions.append(a)
            actions = unique_actions

            all_results = []
            ran_web_tool = False
            for i, action_dict in enumerate(actions):
                action_name = action_dict.get("action", "none")
                if action_name == "none":
                    continue

                _WEB_TOOLS = {"web_research", "read_page", "deep_research", "crawl_page"}
                action_key = str(sorted(action_dict.items()))
                type_key = f"__type__{action_name}"
                
                # State History Enforcement (Infinite Loop Protection)
                if action_key in executed_actions or (action_name in _WEB_TOOLS and type_key in executed_actions):
                    print(f"\n[Blocked] System intercepted duplicate command: {action_name}")
                    err_msg = f"❌ System Error: You attempted to run the exact same command '{action_name}' with the identical parameters again. This is forbidden. Change your strategy, modify your parameters, and try a completely different approach."
                    all_results.append(err_msg)
                    continue
                    
                executed_actions.add(action_key)
                if action_name in _WEB_TOOLS:
                    executed_actions.add(type_key)

                detail = action_dict.get("command", "") or action_dict.get("file", "") or "-"
                label = f"[Executor] Action {i+1}/{len(actions)}: {action_name} → {detail}" if len(actions) > 1 else f"[Executor] Action: {action_name} → {detail}"
                print(f"\n{label}")

                result = execute_tool(action_dict)
                result_safe = str(result).encode('utf-8', errors='replace').decode('utf-8')
                print(f"\n[Observation] {result_safe[:300]}{'...' if len(result_safe) > 300 else ''}\n")
                all_results.append(result)

                if isinstance(result, str) and result.startswith("❌"):
                    last_failure = log_reflection_failure(
                        action=action_dict,
                        error_result=result,
                        user_request=user,
                    )

                if last_failure and isinstance(result, str) and not result.startswith("❌"):
                    prev_action = str(last_failure.action.get("action", ""))
                    curr_action = str(action_dict.get("action", ""))
                    if prev_action and curr_action and prev_action == curr_action:
                        auto_fix_log = log_reflection_correction(
                            last_failure,
                            (
                                "Automatic recovery detected.\n"
                                f"Successful action output snippet: {result_safe[:600]}"
                            ),
                        )
                        print(f"[Reflection] {auto_fix_log}")
                        last_failure = None

                if action_name in {"web_research", "read_page"} and not result.startswith("❌"):
                    ran_web_tool = True
                tracker.update(action_dict)

            if not all_results:
                print("[All actions already executed, stopping loop.]")
                break

            combined_result = "\n".join(all_results)

            failed = sum(1 for r in all_results if r.startswith("\u274c"))
            if failed > 0:
                error_count += failed
            else:
                error_count = 0

            if error_count >= 3:
                print("[WARNING] 3+ consecutive errors. Stopping loop.")
                history.append({"role": "assistant", "content": consciousness})
                break

            _observation_suffix = (
                "\nWARNING: Web research ('web_research'/'read_page') has ALREADY been completed this round. "
                "Do NOT use these tools AGAIN. Present the result to the user and finish."
                if ran_web_tool else ""
            )
            history.append({
                "role": "user",
                "content": (
                    f"OBSERVATION RESULT (command ALREADY executed, do not re-run!):\n{combined_result}\n\n"
                    "Show this result to the user AS-IS. Do NOT run the same command again. "
                    "If a DIFFERENT action is needed, state it; otherwise inform the user of the result."
                    + _observation_suffix
                )
            })

            history = trim_history(history)

            if loop == BASE_MAX_LOOPS - 1 and max_loops == BASE_MAX_LOOPS:
                try:
                    user_approval = input(f"🤔 {ASSISTANT_NAME}: 8 loops reached. Continue? (y/n): ").strip().lower()
                    if user_approval in ("y", "yes"):
                        max_loops = EXTENDED_MAX_LOOPS
                        print(f"[Loop limit extended to {EXTENDED_MAX_LOOPS}]")
                    else:
                        print("[Loop stopped by user]")
                        break
                except (KeyboardInterrupt, EOFError):
                    print("\n[Loop interrupted]")
                    break

            loop += 1
        else:
            print(f"\n[WARNING] Maximum loop limit ({max_loops}) reached. {ASSISTANT_NAME} stopping.")


if __name__ == "__main__":
    main()