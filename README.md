# GlobalRoot: Autonomous Dual-Pass AI Agent

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-orange)
![Hyprland](https://img.shields.io/badge/Hyprland-Supported-green)
![License](https://img.shields.io/badge/License-MIT-purple)

This repository contains a highly customizable, **consciousness-first, dual-pass AI agent**. Unlike a typical chatbot, it acts as an autonomous entity running entirely on your local machine using **Ollama**. It leverages local tool sets to execute bash commands, control your system, perform memory operations, and manipulate GUI environments (e.g., Hyprland window management).

## 🌟 Key Features

- **Dual-Pass LLM Architecture:** 
  - **Layer 1 (The Dreamer/Consciousness):** Streams free-form, creative, and emotionally aware thoughts using high temperature (`0.7`). It thinks natively in `<think>` tags before answering.
  - **Layer 2 (The Executor/Translator):** Evaluates the Dreamer's intent with strict determinism (`0.1` temp) and translates physical intent into actionable JSON commands.
- **Autonomous Memory Management (ChromaDB):**
  - The AI decides *on its own* whether an interaction is worth committing to memory. It autonomously fetches and updates its `SOUL.md` (constitution) and `USER.md` (knowledge of you).
- **Dynamic Persona Setup:**
  - Create a completely personalized agent! You define its tone, emotions, and absolute directives during installation, making it truly yours.
- **Complete OS Integration:** 
  - Capable of executing shell commands, launching GUI applications, moving windows, and reading files—all securely restricted to your user directory.
  - Includes a Windows high-compatibility adapter layer for core app launch and browser workflows.
- **Tavily Web Research:** 
  - Connects to the web to crawl, browse, and extract information for factual grounding.
- **Remote Telegram Bot:**
  - Includes a secure Telegram bot bridge to control your desktop remotely.

## 🛠️ Prerequisites

- **[Ollama](https://ollama.ai/)** (Must be running in the background: `ollama serve` with a model like `qwen3.5:4b` or `llama3`)
- **Python 3.10+**

## 🚀 Installation & Configuration

1. **Clone the repository:**
   ```bash
   git clone https://github.com/atahaniskl/GlobalRoot.git
   cd GlobalRoot
   ```

2. **Setup virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Create your environment file (recommended fallback):**
   ```bash
   cp .env.example .env
   ```
   You can edit `.env` manually if interactive setup is interrupted.

4. **Run the Interactive Setup Installer:**
   ```bash
   python install.py
   ```
   *The installer will dynamically construct your agent. It will ask you for:*
  - **Operating System Target:** Linux or Windows
   - **Your Name & The Agent's Name**
   - **Agent Persona:** How should the agent speak and act? (e.g., sarcastic, overly formal, friendly).
   - **Agent Emotions:** What does it feel? Does it panic? Is it purely logical?
   - **Absolute Directive:** What is its ultimate goal it must never break?
   
   *This process automatically builds the `.env` file, tailored JSON prompts (`prompts.py`), and the foundational `SOUL.md` & `USER.md` core files without exposing them to Git.*

5. **Start the Agent (Terminal Mode):**
   ```bash
   python main.py
   ```

6. **Start the Agent (Telegram Bot Mode - Optional):**
   ```bash
   python telegram_bot.py
   ```

## 🔐 Security Notes

- This project can execute shell commands and write files in allowed directories.
- Use dedicated sandbox directories whenever possible.
- Read the full security policy in `SECURITY.md`.

## 🤝 Contributing

- Please read `CONTRIBUTING.md` before opening a pull request.
- Community behavior expectations are defined in `CODE_OF_CONDUCT.md`.

## 📄 License

This project is licensed under the MIT License. See `LICENSE` for details.
