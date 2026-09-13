# Tela: Login

`core/templates/core/login.html`: página autônoma (não estende `base.html`, não tem menu), com o mesmo
header e footer, card centralizado de 420px com "Entrar", usuário, senha com botão de exibir,
botão `primary block`. Erros como `br-message danger` dentro do card. Bloqueio por tentativas
(django-axes) desabilita o botão e explica.

Não altere: é a única tela sem menu e sem breadcrumb, e a única com `body.dsgov-login`.
Se o órgão tiver logo, ela aparece no header pelo `settings.DSGOV["LOGO"]`. Recuperação de senha, quando
existir, é um link terciário abaixo do botão ("Esqueci minha senha") para as views padrão do Django com
templates no mesmo card.
