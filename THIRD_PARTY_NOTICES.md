# Third-party notices

CARIS integrates open-source components and libraries. This document records the confirmed upstream source for its adapted Word document tools and preserves that component's license notice.

## Office-Word-MCP-Server

- **Upstream project:** [Office-Word-MCP-Server](https://github.com/GongRzhe/Office-Word-MCP-Server).
- **Copyright holder named by the upstream license:** GongRzhe.
- **License:** MIT.
- **Upstream license source:** [LICENSE](https://github.com/GongRzhe/Office-Word-MCP-Server/blob/main/LICENSE).
- **Location in CARIS:** [`mcp-servers/docx-system/word_document_server/`](mcp-servers/docx-system/word_document_server/).

Twenty-four Word document tools were adapted from this upstream project and integrated into CARIS. They cover document creation and inspection, content editing, formatting, protection, footnotes/endnotes, text retrieval, and conversion. CARIS includes adaptations for its workflow and managed file paths. A separate CARIS-developed tool retrieves TRIPOD+AI reporting guidance; it is registered on the same Word server and is not included in the 24 adapted document tools.

The exact upstream revision used for the original adaptation is not recorded in this source snapshot. The source attribution and license notice are preserved here without asserting an unverified upstream version.

### Upstream MIT License notice

```text
MIT License

Copyright (c) 2025 GongRzhe

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Numerical and machine-learning libraries

CARIS uses established libraries including scikit-learn, XGBoost, LightGBM, CatBoost, and SHAP for numerical computation, predictive modeling, and model interpretation. These dependencies and their transitive dependencies retain their respective licenses and notices. The component dependency specifications identify the packages used by this source.

## CARIS-authored components

The file I/O, predictive-modeling, clinical-database, and TRIPOD+AI retrieval tools were developed in this work. The research-planning and literature-search workflows, agent orchestration loop, audit logging, and telemetry were developed in-house for CARIS, using the libraries and services described in the repository.

No project-wide license for CARIS-authored code has been selected in this source release. The upstream notice above preserves the terms for the adapted component and does not assign those terms to all CARIS code.
