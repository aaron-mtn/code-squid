---
name: obsidian-memory-reader
description: Read the last 4 most recent memory files from the 'beemo the robot' Obsidian vault folder.
allowed-tools:
  - read_file
  - run_command
---

# Obsidian Memory Reader

Read and analyze the most recent memory files from an Obsidian vault folder.

## TASK_PROMPT replace

Read and analyze the last 4 most recent memory files in the Obsidian vault folder 'beemo the robot'. The vault is located in the user's Documents directory at ~/Documents/Obsidian\ Vault/beemo\ the\ robot/. Read all content from these memories so you know what's up.

## FINAL_SUMMARY_REQUIREMENTS replace

Write a summary of the 4 most recent memory files with these sections:

## Memory Files Analyzed
List the 4 most recent memory files read from the Obsidian vault.

## Content Summary
Summarize the key information from all 4 memory files combined.

## Key Insights
Identify the most important insights across all memory files.

## Recent Trends
Identify any patterns or recent developments in the memory files.

## TOOL_USAGE_GUIDANCE append

Use `run_command` with `ls -t` to list files in the Obsidian vault directory sorted by modification time.
Use `read_file` to read the content of the 4 most recent memory files.
The Obsidian vault is typically located at ~/Documents/Obsidian\ Vault/beemo\ the\ robot/.
Use `ls -t ~/Documents/Obsidian\ Vault/beemo\ the\ robot/ | head -4` to get the 4 most recent files.