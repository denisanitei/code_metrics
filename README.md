# Code Metrics Tool

* Used for computing code quality, complexity, and architectural metrics on source code (aligned with **ASPICE 4.0 SWE.4** and **HIS OEM Standards**).
* By default, the metrics reports are generated inside the target's build directory under a **`code_metrics`** directory.
* The user can customize the directory in which the metrics report is placed via the `report_out_path` configuration option.
* Other configurations regarding this tool are specified in the target options within the project YAML build configuration.

---

## Configuration Example

```yaml
- !target
  name: YSP_WIN_GCC
  tools:
  - gcc
  - fsmgen
  - datagen
  - console_log
  - absint
  - code_metrics
  type: program
  options:
  - *gcc_options
  - absint:
      dax: project@yzk_platform.dax
      report_out_path: target@__absint__
  - code_metrics:
      report_out_path: target@__cm__
      # HIS Complexity & Size Thresholds
      cc_threshold: 15
      nloc_threshold: 100
      min_comment_ratio: 10
      min_file_comment_ratio: 10
      stmt_threshold: 50
      vocf_threshold: 4.0
      
      # HIS Control Flow & Architecture Thresholds
      param_threshold: 5
      return_threshold: 1
      nesting_depth_threshold: 4
      goto_threshold: 0
      calling_threshold: 10
      calls_threshold: 7
      path_threshold: 200
      rec_threshold: 0
      dead_code_threshold: 0
      
      # OEM Quality Audit & Coding Standard Thresholds
      call_depth_threshold: 6
      file_lines_threshold: 1200
      static_declarations_threshold: 20
```

---

## Configuration Parameters

All parameters are specified as child keys under the `code_metrics` section of the target options in the YAML configuration.

| Parameter | Type | Default | Metric / Standard | Description |
| :--- | :---: | :---: | :--- | :--- |
| `report_out_path` | `str` | *target build dir* | General | Output directory for the generated XML, HTML, and JUnit reports. Relative paths are resolved against project root. |
| `cc_threshold` | `int` | `20` | HIS `v(G)` / cyclomatic | Maximum allowed classic McCabe Cyclomatic Complexity per function ($M = 1 + \text{decision points}$, excluding `&&`/`||` short-circuit branches). Evaluates decision density. Recommended OEM limit: `<= 15`. |
| `nloc_threshold` | `int` | `200` | HIS `COMF` / size | Maximum allowed Non-Comment Lines of Code per function or file. Recommended limit: `<= 100` (functions), `<= 200` (files). |
| `min_comment_ratio` | `float` | `10.0` | HIS `CDRP` / function comments | Minimum allowed function comment density ratio (%), including header/Doxygen comments immediately above the function and inline body comments, calculated as: $\frac{\text{comments}}{\text{NLOC} + \text{comments}} \times 100$. |
| `min_file_comment_ratio` | `float` | `10.0` | HIS `CDRP` / file comments | Minimum allowed file comment density ratio (%) across the entire translation unit (all file-level and function-level comments), calculated as: $\frac{\text{comments}}{\text{NLOC} + \text{comments}} \times 100$. |
| `param_threshold` | `int` | `5` | HIS `PARAM` / stability | Maximum allowed formal parameters per function. Evaluates interface clarity and coupling. |
| `return_threshold` | `int` | `1` | HIS `RET` / stability | Maximum allowed return points per function (MISRA C single exit point compliance). |
| `nesting_depth_threshold` | `int` | `4` | HIS `LEVEL` / testability | Maximum control structure nesting depth (`if`, `for`, `while`, `switch`). OEM limit: `<= 7`. |
| `stmt_threshold` | `int` | `50` | HIS `STMT` / analysability | Maximum executable statements per function body. |
| `vocf_threshold` | `float` | `4.0` | HIS `VOCF` / analysability | Maximum allowed HIS Language Scope / Vocabulary Frequency per function, calculated as $\frac{N_1 + N_2}{n_1 + n_2}$ (total lexical tokens divided by distinct lexical tokens). |
| `goto_threshold` | `int` | `0` | HIS `GOTO` / changeability | Maximum allowed `goto` jump statements per function (MISRA C Rule 15.1 forbids `goto`). |
| `calling_threshold` | `int` | `10` | HIS `CALLING` / Fan-In | Maximum number of different functions calling this function across the build. Measures architectural coupling. |
| `calls_threshold` | `int` | `7` | HIS `CALLS` / Fan-Out | Maximum distinct functions called by this function. Measures unit test isolation complexity. |
| `path_threshold` | `int` | `1000` | HIS `PATH` / stability | Maximum static execution paths through the function. OEM limit: `<= 200`. |
| `rec_threshold` | `int` | `0` | HIS `REC` / stability | Maximum recursive calls (direct or indirect). Automotive safety standards forbid recursion. |
| `dead_code_threshold` | `int` | `0` | HIS `DEAD` / stability | Maximum unreachable / dead code statements following unconditional termination. |
| `call_depth_threshold` | `int` | `6` | OEM Call Graph Depth | Maximum call graph invocation depth starting from this function through its call hierarchy. OEM limit: `<= 6`. |
| `file_lines_threshold` | `int` | `1200` | OEM File Size | Maximum total line count (including comments and blank lines) in a single translation unit. OEM limit: `<= 1200`. |
| `static_declarations_threshold` | `int` | `20` | OEM Static Declarations | Maximum number of unique `static` declarations (variables and functions) in a file. OEM limit: `<= 20`. |

---

## ASPICE 4.0 SWE.4 & HIS Standard Alignment

The tool enforces metrics derived from the **Hersteller Initiative Software (HIS)** source code metrics consortium and satisfies the verification requirements of **ASPICE 4.0 Process SWE.4 (Software Detailed Design and Unit Construction)**:

| HIS Metric Code | Metric Name | Recommended Range | Scope | Quality Objective |
| :--- | :--- | :---: | :---: | :--- |
| **`v(G)`** | Cyclomatic Complexity | $1 \le v(G) \le 10$ (Warn: $11-15$, Fail: $> 15$) | Function | Low control flow branching, high testability |
| **`COMF`** | Lines of Code (NLOC) | $1 \le \text{NLOC} \le 100$ | Function / File | Readability, concise modular units |
| **`CDRP`** | Comment Density Ratio | $\ge 8.0\%$ (Default: $10.0\%$) | Function / File | Self-documenting code base (includes function header comments) |
| **`PARAM`** | Number of Parameters | $0 \le \text{PARAM} \le 5$ | Function | Minimal function interface coupling |
| **`RET`** | Number of Return Points | $\text{RET} = 1$ | Function | Deterministic exit point, easy resource cleanup |
| **`LEVEL`** | Max Nesting Depth | $1 \le \text{LEVEL} \le 4$ (OEM: $\le 7$) | Function | Comprehensibility and unit test path coverage |
| **`STMT`** | Executable Statements | $1 \le \text{STMT} \le 50$ | Function | Single responsibility principle |
| **`VOCF`** | Language Scope (Vocabulary Frequency) | $1.0 \le \text{VOCF} \le 4.0$ | Function | Low token repetition, maintainable function scope |
| **`GOTO`** | GOTO Statements | $\text{GOTO} = 0$ | Function | Structured programming compliance |
| **`CALLING`** | Fan-In (Callers) | $0 \le \text{CALLING} \le 10$ | Function | Modular dependency management |
| **`CALLS`** | Fan-Out (Callees) | $0 \le \text{CALLS} \le 7$ | Function | Encapsulation and reduced ripple effects |
| **`PATH`** | Static Path Count | $1 \le \text{PATH} \le 200$ | Function | Verifiable exhaustive path testing |
| **`REC`** | Recursion Count | $\text{REC} = 0$ | Function | Bounded stack depth and timing determinism |
| **`DEAD`** | Unreachable Statements | $\text{DEAD} = 0$ (OEM: $\le 20$) | Function / File | Elimination of dead code |
| **`DEPTH`** | Call Graph Depth | $1 \le \text{DEPTH} \le 6$ | Function | Predictable call hierarchies |
| **`FILE_LINES`** | Total File Lines | $\le 1200$ | File | Manageable file modularity |
| **`STATIC_DECL`** | Static Declarations | $\le 20$ | File | Encapsulation, thread safety, bounded state |
| **`IF_ELSE`** | IF Without ELSE | $0$ | Function | Complete decision branches (MISRA 15.7) |
| **`UNUSED_VAR`** | Non-used Variables | $0$ | Function | Clean allocations, no redundant tokens (MISRA 2.2) |

---

## OEM Quality Audit & Metric Distribution Summary

The generated interactive HTML report includes a dedicated **OEM Quality Audit & Metric Distribution Summary** section. This table provides bin distribution counts with live status evaluation:

| Audit Parameter / Metric Bin | OEM Target Range | Audit Status Criteria |
| :--- | :---: | :--- |
| **Cyclomatic $\le 15$** | $\le 15$ | PASS 🟢 (Standard complexity) |
| **Cyclomatic $> 15-20$** | $> 15 \text{ and } \le 20$ | WARN 🟡 (Acceptable with justification) |
| **Cyclomatic $> 20-30$** | $> 20 \text{ and } \le 30$ | WARN 🟡 (High complexity, refactoring suggested) |
| **Cyclomatic $> 30$** | $> 30$ | FAIL 🔴 (Critical complexity violation) |
| **Unreachable statements $\le 20$** | $\le 20$ statements | PASS 🟢 (Acceptable defensive code) |
| **Unreachable statements $> 20-30$** | $> 20 \text{ and } \le 30$ | WARN 🟡 (Elevated dead code) |
| **Unreachable statements $> 30$** | $> 30$ statements | FAIL 🔴 (Excessive dead code) |
| **Static Declarations $\le 20$** | $\le 20$ per file | PASS 🟢 (Normal static file state) |
| **Static Declarations $> 20$** | $> 20$ per file | WARN 🟡 (High file-scope state encapsulation) |
| **Static Path Count $\le 200$** | $\le 200$ paths | PASS 🟢 (Verifiable path count) |
| **Static Path Count $> 200$** | $> 200$ paths | WARN 🟡 (Combinatorial explosion, refactor required) |
| **Maximum nesting of control structure $\le 7$** | $\le 7$ levels | PASS 🟢 (Structured control flow) |
| **Maximum nesting of control structure $> 7$** | $> 7$ levels | FAIL 🔴 (Excessive nesting, review required) |
| **Call graph depth $\le 6$** | $\le 6$ call levels | PASS 🟢 (Bounded architectural depth) |
| **Call graph depth $> 6$** | $> 6$ call levels | WARN 🟡 (Deep call stack, potential stack risk) |
| **IF without ELSE** | $= 0$ violations | PASS 🟢 when $0$, FAIL 🔴 when $> 0$ |
| **Number of Lines in a file $\le 1200$** | $\le 1200$ lines | PASS 🟢 (Standard file length) |
| **Number of Lines in a file $> 1200$** | $> 1200$ lines | WARN 🟡 (Oversized file, split recommended) |
| **Non used variables** | $= 0$ violations | PASS 🟢 when $0$, FAIL 🔴 when $> 0$ |
| **Number of functions** | All detected functions | INFO ℹ️ (Total function inventory count) |
| **MISRA - functions to be checked** | C/C++ source functions | INFO ℹ️ (Excludes assembly / non-C functions) |
| **MISRA - functions checked** | Analyzed functions | INFO ℹ️ (Functions evaluated by rule engine) |

> **Interactive Filtering**: Clicking any row in the OEM Quality Audit summary in the HTML report automatically applies the corresponding filter to the Functions or Files table below it for instant inspection.

---

## Output Artifacts

Running the `code_metrics` tool produces three main artifacts:

1. **XML Metrics Report (`<target>.xml`)**:
   Full machine-readable hierarchy detailing every analyzed function and source file with all computed metrics (CCN, NLOC, parameters, tokens, paths, dead code, call depth, file lines, static declarations, etc.).
2. **Interactive HTML Dashboard (`<target>.html`)**:
   Standalone, self-contained dashboard (no external CDN or internet connection required). Contains:
   - Executive quality KPIs and pass/fail rate badges.
   - Interactive Cyclomatic Complexity and NLOC distribution bar charts.
   - OEM Quality Audit summary with clickable filter triggers.
   - Sortable, searchable Function and File tables with active filter chips.
   - CSV export capability for custom spreadsheet analysis.
   - Threshold Limits configuration reference table.
3. **CI/CD JUnit Report (`junit_report.xml`)**:
   Standard JUnit XML test suite format mapping functions and files to test cases. Any threshold violation generates a `<failure>` element with human-readable diagnostic messages, allowing continuous integration pipelines (Jenkins, GitLab CI, Azure DevOps) to fail builds or display test results natively.

---

## Standalone CLI Usage

The core metric analyzer can also be executed directly via command line without the Waf build system:

```bash
python hfcca.py [options] [PATH or FILE] ...
```

### Supported CLI Flags

* `--xml=<output_file.xml>`: Write full metric results to XML format.
* `--input=<file_list.txt>`: Read target file paths line-by-line from a text file.
* `-e <pattern>`, `--exclude=<pattern>`: Exclude files matching regex patterns (e.g., `-e ".*test.*"`).
* `-t <num>`, `--working-threads=<num>`: Multi-threaded parallel file analysis (default: CPU core count).
* `-C`, `--no-preprocessor-count`: Ignore preprocessor directive lines (`#if`, `#define`, `#include`) in line count.
* `-s <threshold>`, `--sort=<threshold>`: Filter functions exceeding a specific complexity threshold.
