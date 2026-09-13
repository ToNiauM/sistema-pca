# Tela: Wizard (fluxo em etapas)

Use `br-wizard` (ver `componentes/wizard.md`) apenas para cadastros longos com etapas naturais
(dados pessoais → documentos → revisão). Implementação determinística: uma view por etapa, estado na
sessão ou num registro "rascunho", cada etapa é um formulário Django normal dentro de
`wizard-panel-content`; os botões do rodapé do wizard são os do componente (`wizard-btn-prev secondary`,
`wizard-btn-next primary`, `wizard-btn-canc`). A última etapa é uma revisão em `dl.dsgov-detalhe` com
botão "Concluir". Não use JS próprio para trocar etapas: cada "Avançar" é um POST.
