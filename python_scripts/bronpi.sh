#!/bin/bash
customer_code=$1
authorization=$2
values=$3

# Construction propre du JSON avec printf
json_data=$(printf '{
  "id_product": "E20CC516-7ADC-4936-B690-A7686F3BBE5E",
  "id_device": "C3211D5C-9FFD-42EB-9F9F-3377BA333102",
  "Protocol": "RWMSmaster",
  "BitData": [8],
  "Endianess": ["L"],
  "Freq": 0,
  "Items": [32919],
  "Values": [%s],
  "Masks": [65535]
}' "$3")

# Déclaration correcte de la variable request
request="curl -X POST \
--header 'Content-Type: application/json' \
--header 'Accept: application/json' \
--header 'customer_code: $1' \
--header 'id_brand: 0' \
--header 'authorization: $2' \
--header 'local: false' \
-d '$json_data' \
'https://bronpi.agua-iot.com/deviceRequestWriting'"

eval "$request"
