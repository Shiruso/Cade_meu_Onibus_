# 🚌 Monitor de Ônibus & BRT - Rio de Janeiro

Aplicação para visualização e rastreamento em tempo real da frota de ônibus e BRT da cidade do Rio de Janeiro, utilizando dados abertos da plataforma **DATA.RIO**.

---

## 🛠️ Como Funciona
1. **Busca e Rotas**: O usuário informa a linha desejada. O aplicativo consulta o banco de dados local em SQLite (`gtfs_rio.db`) para carregar o trajeto e os pontos de parada no mapa.
2. **Localização em Tempo Real**: Simultaneamente, o app faz requisições às APIs de GPS para obter a posição atualizada dos veículos e exibe os ícones personalizados das frotas no mapa.
3. **Atualização Automática**: O arquivo `config.json` verifica a versão dos dados no repositório. Caso haja atualizações, o app realiza o download dos arquivos necessários automaticamente.

---

## 🗄️ Fontes de Dados e APIs

### GTFS (General Transit Feed Specification)
- **[GTFS RJ (DATA.RIO)](https://www.data.rio/documents/b577e4c4c0924888823b630bbdb2c6fd/explore)**: Contém as informações estáticas do sistema de transporte (linhas, trajetos, horários e pontos de parada).

### APIs de GPS em Tempo Real (SPPO - Ônibus Urbanos)
*Nota: A [API antiga de GPS](https://www.data.rio/documents/PCRJ::transporte-rodovi%C3%A1rio-api-de-gps-de-%C3%B4nibus-urbanos-sppo-descontinuada/about?path=) foi descontinuada.*

- **[API Conecta (Beta)](https://www.data.rio/documents/2a5d133b3e914065b9ece3790f5e5685/about)**: API principal em uso. Apresenta excelente estabilidade para frotas de ônibus urbanos (SPPO).
- **[API SistemaRIO (Beta)](https://www.data.rio/documents/32cdc652a9c84018a4c9bde73516ec59/about)**: Em fase de testes pela prefeitura.
- **[API Zirix (Beta)](https://www.data.rio/documents/fd2c79eaf6aa424aab2516f261c9ffda/about)**: Em fase de testes pela prefeitura.

### APIs do BRT
- **[API de GPS do BRT](https://dados.mobilidade.rio/gps/brt)**: Endpoint utilizado para capturar as coordenadas dos veículos do BRT via payload JSON.
- Documentação técnica no portal: [Documentação BRT DATA.RIO](https://www.data.rio/documents/PCRJ::transporte-rodovi%C3%A1rio-api-de-gps-do-brt/about?path=).

---

## ⚡ Otimização do Banco de Dados

Processar diretamente os arquivos de texto (`.txt`) brutos do GTFS em dispositivos móveis exige alto processamento e memória. 

Para resolver isso, foi desenvolvido o script em Python **`gerar_banco.py`**, responsável por:
1. Processar os arquivos `.txt` do GTFS oficial.
2. Converter e estruturar os dados em um banco **SQLite local (`gtfs_rio.db`)**.
3. Reduzir drasticamente o tempo de leitura e o uso de memória no dispositivo Android.

---

## 🎨 Personalização
- O mapa conta com **ícones visuais personalizados** representando as frotas e viações locais da cidade (como a Viação Jabour).

---

## 📌 Considerações e Contribuições
Este projeto foi desenvolvido para fins acadêmicos e de aprendizado em desenvolvimento de software e integração de dados abertos.

Contribuições, correções de bugs e *pull requests* são super bem-vindos!
