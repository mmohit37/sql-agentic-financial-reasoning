# FINER XBRL Paper Notes

## Dataset Overview

The FINER benchmark is a domain-specific evaluation tool used to test large language models (LLMs) on complex financial reasoning tasks that rely on eXtensible Business Reporting Language (XBRL) data.
Here is a summary of how FINER uses XBRL data:
Data Collected and Structure
The FINER benchmark collects financial data structured using XBRL.

• Type of Data Collected: The task in FINER requires LLMs to perform Financial Numeric Entity Recognition (FINER). Specifically, it involves labeling tokens within XBRL financial documents.

• Structure of Data: The data is drawn from XBRL financial documents. The benchmark requires labeling tokens with one of 139 fine-grained entity types. This process is a key step for financial information extraction in regulated domains.
Value for Evaluating Large Language Models (LLMs)
FINER, along with the Formula benchmark, serves to evaluate LLMs on domain-specific benchmarks that demand specialized tactics and knowledge, focusing on financial analysis.

• Testing Domain-Specific Knowledge: Strong performance on FINER depends on an LLM's mastery of specialized concepts and tactics related to financial analysis and XBRL rules.

• Need for Detailed Context: The benchmark is valuable because high performance depends on retaining detailed, task-specific knowledge and requiring precise domain knowledge (e.g., financial concepts, XBRL rules). This contrasts with tasks that benefit more from concise, high-level instructions.

• Benchmarking Context Adaptation: Frameworks like ACE (Agentic Context Engineering) use FINER to demonstrate that structured, evolving contexts (or "playbooks") lead to large gains in domain-specific reasoning, achieving an average performance gain of 8.6% over strong baselines. The challenge of FINER highlights the need for specialized context adaptation techniques to handle knowledge-intensive applications.

## Benchmark Methodology

The evaluation of large language models (LLMs) on specialized financial tasks, often studied in the context of frameworks like ACE, uses several benchmarks, notably FiNER and Formula.

Main Tasks and Benchmarks
The LLM evaluation focused on financial analysis uses two domain-specific benchmarks:
1. FiNER (Financial Numeric Entity Recognition):
    ◦ Task: This benchmark requires the LLM to perform Financial Numeric Entity Recognition.
    ◦ Goal: The specific task is labeling tokens within eXtensible Business Reporting Language (XBRL) financial documents.
    ◦ Specificity: Models must assign tokens to one of 139 fine-grained entity types, which is a critical step for financial information extraction in regulated environments.
2. Formula:
    ◦ Task: This benchmark evaluates numerical reasoning capabilities.
    ◦ Goal: It involves extracting values from structured XBRL filings and subsequently performing computations to generate answers for financial queries.
These domain-specific benchmarks demand the LLM’s mastery of specialized concepts and tactics related to financial analysis and XBRL rules, contrasting with general tasks that benefit only from concise, high-level instructions.

Performance Metrics and Criteria
For both the FiNER and Formula benchmarks, performance is measured using accuracy.

• Criteria: Accuracy is calculated as the proportion of predicted answers that exactly match the ground truth.

• Evaluation Settings: Models are evaluated either through offline context adaptation (optimized on the training split and evaluated on the test split using pass@1 accuracy) or online context adaptation (evaluated sequentially on the test split, updating the context after each sample).

## Prompt Structure and Model Setup

The FINER benchmark is used within the context of the Agentic Context Engineering (ACE) framework to evaluate Large Language Models (LLMs) on domain-specific financial reasoning tasks. The experiment design focuses on context adaptation—modifying inputs with instructions and strategies, rather than updating model weights.
Here is a breakdown of how the experiments are designed, the prompting structure, and the models/baselines compared:
1. Experimental Design and Prompt Structure (ACE Framework)
The ACE framework treats the context as an evolving playbook that accumulates, refines, and organizes strategies over time. The goal is to provide detailed, task-specific knowledge required for complex financial analysis.
Adaptation Settings:
The FINER benchmark is used for two adaptation settings:
1. Offline Context Adaptation: Methods are optimized on the training split of the data and then evaluated on the test split using pass@1 accuracy.
2. Online Context Adaptation: Methods are evaluated sequentially on the test split. For each sample, the model first generates a prediction using the current context, and then the context is updated based on that sample.
Prompting Structure (ACE Generator for FiNER):
The prompt structure for the ACE Generator on FiNER focuses on providing the model with a curated playbook and reflection insights to guide its reasoning.
• The generator is instructed to act as an analysis expert answering questions using its knowledge, a curated playbook, and a reflection of previous mistakes.
• The model must read the playbook carefully and apply relevant strategies, formulas, and insights, paying attention to common mistakes.
• The model must show its reasoning step-by-step and double-check calculations before providing the final answer.
• The output is required to be a JSON object containing the reasoning, a list of relevant bullet_ids from the playbook, and the final_answer.
Context Creation via Agentic Architecture:
The ACE framework uses a three-part agentic architecture to create the evolving context:
• Generator: Produces reasoning trajectories and final answers for queries.
• Reflector: Critiques the Generator's trace by comparing the predicted answer with the ground truth to diagnose errors (conceptual, calculation, or misapplied strategies) and extracts actionable insights and key principles to avoid future mistakes.
• Curator: Synthesizes the lessons from the Reflector into compact delta context items, which are merged deterministically into the existing context playbook. This process ensures incremental delta updates rather than costly monolithic rewrites, preserving detailed knowledge.
Crucially, in the domain-specific setting (FiNER), the ACE framework is evaluated both with and without ground-truth (GT) labels available to the Reflector during adaptation, although results suggest adaptation depends critically on feedback quality.

Key Findings on FiNER:
The results showed that ACE consistently outperformed the strong baselines on domain-specific benchmarks like FiNER, achieving an average performance gain of 8.6% when ground-truth answers were available for reflection. This highlights the advantage of structured and evolving contexts for tasks demanding precise domain knowledge, such as financial concepts and XBRL rules.
To visualize this, imagine training an analyst: ICL is like giving them a static manual, GEPA/MIPROv2 is like giving them an aggressively optimized but short summary, while ACE is like giving them a comprehensive, continuously updated playbook of detailed rules and past mistakes to consult every time they encounter a complex financial problem.

## Reproduction Plan
The reproduction of the results for the Agentic Context Engineering (ACE) framework, particularly on financial analysis benchmarks like FiNER and Formula, requires specific models, datasets, and the implementation of a modular, agentic workflow.

1. Model Requirements and Architecture
• Base Large Language Model (LLM): The core LLM used for the Generator, Reflector, and Curator components must be the DeepSeek-V3.1 model. To ensure fairness, the same LLM is used across all three roles.
• Agentic Framework: The experimental setup relies on the ACE framework, which uses a specialized agentic architecture that separates the roles of:
    ◦ Generator: Produces reasoning trajectories and final answers for queries.
    ◦ Reflector: Critiques the Generator's traces, comparing predictions to ground truth (when available) to diagnose errors and extract insights,.
    ◦ Curator: Synthesizes the Reflector's lessons into compact delta entries (structured, itemized bullets) and integrates them into the Playbook,.
• Adaptation Settings: Experiments must be conducted in two settings:
    ◦ Offline Context Adaptation: Context is optimized on the training split. The maximum number of Reflector refinement rounds and the maximum number of epochs are set to 5.
    ◦ Online Context Adaptation: Context is evaluated sequentially on the test split, updating the Playbook after each sample.
• Batch Size: Context adaptation should use a batch size of 1, meaning a delta context is constructed from each sample.

2. Data and Datasets
The reproduction requires access to the full datasets for financial analysis:
• FiNER (Financial Numeric Entity Recognition): Used for tasks involving labeling tokens within eXtensible Business Reporting Language (XBRL) financial documents. This task involves classifying tokens into one of 139 fine-grained entity types.
• Formula: Used for tasks requiring numerical reasoning, specifically extracting values from structured XBRL filings and performing computations to answer financial queries.
• Data Splits: All datasets must follow the original train/validation/test splits.

3. Preprocessing and Context Engineering Steps
The core preprocessing is the Context Engineering itself, which dictates how prompts are structured and contexts are updated.
• Prompting the Generator (FiNER/Formula): The Generator is prompted to act as an analysis expert, reading a Playbook of strategies and insights. It is instructed to show reasoning step-by-step and double-check calculations. The output must be a specific JSON object containing the reasoning, a list of relevant bullet_ids from the playbook, and the final_answer (Figure 12).

• Prompting the Reflector (FiNER/Formula): The Reflector is prompted to diagnose the model’s reasoning trace by analyzing the gap between the predicted and ground-truth answers. It must identify the root cause of errors and provide a key_insight (strategy or principle) to remember,. It also assigns tags (helpful, harmful, neutral) to the bullet points used by the Generator (Figure 13).
• Prompting the Curator (FiNER/Formula): The Curator identifies ONLY new insights missing from the current Playbook based on the Reflection, avoiding redundancy. It formats its response as a JSON object of operations (e.g., ADD), specifying the section and content for the new context entry (Figure 14),.
• Context Management: Crucially, the Playbook updates are performed using incremental delta updates. Lightweight, non-LLM logic is used for deterministic merging, pruning, and de-duplication of itemized context bullets,.

4. Evaluation Criteria
• Metric: Performance must be measured using accuracy.
• Definition: Accuracy is calculated as the proportion of predicted answers that exactly match the ground truth.
• Offline Evaluation: Evaluation uses pass@1 accuracy on the test split