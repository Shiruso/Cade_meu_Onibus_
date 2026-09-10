Este programa depende dos dados fornecidos pela DATA.RIO. Entre eles temos:

O GTFS do RJ: https://www.data.rio/documents/b577e4c4c0924888823b630bbdb2c6fd/explore 
ele que é responsável pelos trajetos exibidos no mapa, os nomes das linhas, pontos de paradas, etc...

E tbm o primordial que são as API

Antigamente tinha uma única api que foi descontinuada: https://www.data.rio/documents/PCRJ::transporte-rodovi%C3%A1rio-api-de-gps-de-%C3%B4nibus-urbanos-sppo-descontinuada/about?path=

E as novas API's são essas:
"Conecta" que está em fase beta: https://www.data.rio/documents/2a5d133b3e914065b9ece3790f5e5685/about (tá funcionando que é uma beleza, só os BRT que ele não puxa)
"SistemaRIO" que tbm está em beta:https://www.data.rio/documents/32cdc652a9c84018a4c9bde73516ec59/about (até o momento só retorna dados inválidos, sla pq)
"Zirix" que tbm está em beta:https://www.data.rio/documents/fd2c79eaf6aa424aab2516f261c9ffda/about (essa eu tentei colocar, mas não tem nenhuma documentação dela no Google Colab)


Pro BRT tem esse aqui "API de GPS do BRT":https://www.data.rio/documents/PCRJ::transporte-rodovi%C3%A1rio-api-de-gps-do-brt/about?path= (eu tentei usar esse trem, mas não funcionou - acho que eles ainda vão ajeitar)
Pra pegar os dados desse é só jogar o url https://dados.mobilidade.rio/gps/brt que ele vai cuspir um json cabuloso que você pode filtrar.


E bom, baixar isso tudo num celular "veio podi" não dá certo, é muito pesado e ler arquivos TXT é horrível, demora pra chuchu.
Então, eu fiz um scriptzinho em python (gerar_banco.py) que pega essa joça toda de GTFS e cria um arquivo gtfs_rio.db (SQLite eu acho) que é muito mais fácil de lidar e mais leve.

Então o app basicamente pega o mapa, pega a linha que o usuário digitou, busca no arquivo gtfs_rio.db, taca os trajetos no mapa, enquanto isso ele faz a requisição a API e cospe o resultado no mapa e GG.

Ah, quanto ao config.json que coloquei aqui no repositório ele só serve pro app ver se eu fiz alguma atualização, se sim ele baixa os arquivos novos, senão ele fica de xereco.

Deu um trabalho do carai fazer esse trem, eu coloquei até os ônibuzinhos iguais ao da viação Jabour que eu pego as vezes e ficou do caralho.

Enfim, eu criei esse arquivo só pra listar os locais onde você pode pegar os arquivos e a documentação das API. Eu não manjo muito de programação, só sei o arroz com feijão que aprendi no youtube,
então foi mal ae caso eu tenha feito alguma merda que não esteja funcionando direito.
