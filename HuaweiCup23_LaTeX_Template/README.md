# Huawei Cup 23 LaTeX Template

This folder contains a LaTeX version of the supplied Word paper template for the 23rd Huawei Cup China Post-Graduate Mathematical Contest in Modeling.

## Files

- `HuaweiCup23_LaTeX_Template.tex` - main template file
- `figures/` - logo assets extracted from the original Word template

## Compile

Compile with XeLaTeX or LuaLaTeX:

```text
xelatex HuaweiCup23_LaTeX_Template.tex
```

Edit the metadata commands near the top of the `.tex` file:

```latex
\newcommand{\University}{Your University}
\newcommand{\TeamNumber}{Your Team Number}
\newcommand{\TeamMemberOne}{First Author}
\newcommand{\TeamMemberTwo}{Second Author}
\newcommand{\TeamMemberThree}{Third Author}
\newcommand{\PaperTitle}{Your Paper Title}
```

The template preserves the visible structure of the Word source: contest heading,
university, team number, three team members, and title. It also provides an English
paper skeleton containing:

- a table of contents;
- an abstract and keywords block;
- four numbered heading levels: section, subsection, subsubsection, and paragraph;
- templates for problem restatement, data description, assumptions, model formulation,
  solution method, results, validation, sensitivity analysis, and conclusions;
- equation, figure, and table examples with cross-references and caption conventions;
- a numbered reference section using `thebibliography`; and
- optional appendices for supplementary derivations and results.

The competition's final submission rules and paper-format requirements should still
be checked against the current official submission page.
