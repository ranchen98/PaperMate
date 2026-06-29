FROM elastic/elasticsearch:8.13.4

RUN ./bin/elasticsearch-plugin install --batch \
    https://release.infinilabs.com/analysis-ik/stable/elasticsearch-analysis-ik-8.13.4.zip
