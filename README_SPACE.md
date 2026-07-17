---
title: Enterprise HR Policy AI Assistant
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
---

# Enterprise HR Policy AI Assistant

An **Agentic RAG** chatbot that answers employee HR-policy questions
strictly from a company's own uploaded policy PDFs — every answer is
grounded, cited (document + page), and the system refuses rather than
guesses when it isn't confident.

This demo comes pre-seeded with a sample HR handbook so you can try it
immediately — ask something like *"How many casual leave days do I get
per year?"* Upload your own PDF from the Documents page to try it with a
different policy.

**Storage on this free-tier Space is ephemeral** — the container
filesystem resets on every Space restart/rebuild. Anything you upload
here will not survive a restart; only the pre-seeded demo document
reappears automatically (it re-ingests itself on every cold start). This
is a portfolio/demo deployment, not a production one — see the full repo
for the architecture rationale behind that trade-off (ADR-012).

Full source, design docs, and local setup instructions:
https://github.com/arshitbh25/enterprise-hr-assistant
