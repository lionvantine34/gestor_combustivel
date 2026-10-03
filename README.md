# Rota Verde — Gerenciador de combustível para autoescolas

MVP web executado localmente, com frontend em HTML/CSS/JavaScript, API em Python e banco SQLite. Não exige instalação de frameworks.

## Como iniciar no Windows

1. Instale Python 3.10 ou superior.
2. Abra o PowerShell nesta pasta.
3. Execute `py app.py` (ou `python app.py`).
4. Acesse `http://127.0.0.1:8000` no navegador.
5. No primeiro acesso, crie o administrador. Depois, o administrador cadastra gestores e instrutores na seção **Usuários**.

O arquivo do banco aparece em `data/autoescola.sqlite3` após iniciar. Guarde cópias de segurança desse arquivo. Ele não deve ser compartilhado publicamente: contém dados de usuários e da operação.

## Publicar um endereço para apresentação

O projeto inclui `render.yaml` para publicar como serviço web no Render. Essa configuração usa plano com disco persistente para preservar o SQLite entre reinícios e implantações. O plano, armazenamento e eventuais limites/preços são definidos pelo Render e podem mudar; confira as condições atuais antes de criar o serviço.

1. Crie um repositório GitHub seu e coloque nele os arquivos que estão dentro desta pasta (incluindo `render.yaml`). Não adicione a pasta `data/` nem o banco de dados ao repositório.
2. No Render, crie um **Blueprint** e conecte esse repositório.
3. Durante a criação, defina `SETUP_KEY` como um código longo e aleatório. Guarde esse código em local privado; ele só será solicitado para criar a primeira conta administradora.
4. Aguarde a implantação e abra o endereço `.onrender.com` que o Render fornecer. A primeira conta precisará do código de cadastro.
5. Depois de criar o administrador, o primeiro cadastro é bloqueado. Para apresentar, entre com a conta e mostre a interface.

Não use dados pessoais ou reais de clientes na demonstração. Um link público torna a tela acessível a qualquer pessoa, embora as páginas de dados exijam login. O host mantém o banco no disco persistente configurado; não publique nem envie esse arquivo para o GitHub.

## Perfis

| Perfil | Permissões |
|---|---|
| Administrador | Gerenciar contas e perfis; gerir frota; registrar e consultar lançamentos da autoescola; ajustar fatores de emissão. |
| Gestor | Cadastrar/arquivar veículos; lançar abastecimentos; consultar os registros da frota. |
| Instrutor | Consultar veículos; lançar abastecimentos; consultar apenas os próprios registros. |

As permissões são verificadas também no backend. O cadastro inicial só funciona enquanto não existir nenhum usuário. O administrador cria as demais contas.

## Cálculos

- Custo: litros × preço por litro.
- Consumo: distância informada ÷ litros abastecidos (km/L).
- CO₂ estimado: litros × fator em kg CO₂/L.

Os fatores iniciais são 2,23 kg CO₂/L para gasolina C e 2,46 kg CO₂/L para etanol hidratado, conforme a tabela de fatores 2004–2024 do [Inventário Nacional de Emissões Atmosféricas por Veículos Automotores Rodoviários (ano-base 2024)](https://www.gov.br/transportes/pt-br/assuntos/sustentabilidade/mudanca-do-clima/0_ineavar_2025.pdf). O sistema rotula esse resultado como estimativa de CO₂ direto da combustão. Não representa o ciclo de vida completo, não é uma medição no escapamento e não calcula impacto climático líquido. Fatores podem ser ajustados pelo administrador; lançamentos anteriores preservam o fator aplicado no momento em que foram registrados.

## Escopo e próximos passos

Esta versão é adequada para demonstração e desenvolvimento local. Antes de publicar para uso real, configure HTTPS, cookie `Secure`, backup automatizado, política de recuperação de senha, trilha de auditoria, proteção contra abuso, hospedagem do banco em armazenamento persistente e revisão de segurança. O servidor padrão escuta somente em `127.0.0.1`.

Este MVP ainda não importa dados, exporta planilhas/PDF, sincroniza entre computadores, nem controla preenchimento de odômetro contínuo. Cada usuário deve receber uma conta individual e não compartilhar senha.
