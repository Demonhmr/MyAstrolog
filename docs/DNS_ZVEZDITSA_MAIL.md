# DNS zvezditsa.ru для писем с кодом входа (внести в reg.ru)

Письма уходят с сервера 137.22.150.127 (exim), From: no-reply@zvezditsa.ru, конверт: no-reply@volpen.ru.
Подпись DKIM ставит exim ключом /etc/exim4/dkim/zvezditsa.ru.private (селектор `dkim`). Ключ публичный — секрета здесь нет.

| Тип | Имя (субдомен) | Значение |
|-----|----------------|----------|
| TXT | `dkim._domainkey` | `v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqfvegwg33zGo0QoqyoJqTRRFg+f7jF+QbqqV2rvzfnhrnV3sqz7WQQmUZpeh0G88NvkIT+Mf+V3XrUwvZfv2VPcksOBkOz4MmgTV2oJL9K85fU2Kdioin9hl0ySdSmAt3jwNPaUA7efJ4Itpkpg2c3bRh8N+cCOMb36SaBSTB2LSSQ2chDs3yCNK1An7eCn7aas9D0yjHV1m9O041eROtkw6qHEMhxP3TjjJsFgrrX8Ujnl/1Q/lmlw+pTIE62+QxX16t9AmR4rpfKGFuoE1Y167SWvEkxHq8HccNU1wqkU6vCvaQ7+zvOhnXpmFapngTi+PnynYRvcfFYgFZTnQvQIDAQAB` |
| TXT | `@` | `v=spf1 ip4:137.22.150.127 ~all` |
| TXT | `_dmarc` | `v=DMARC1; p=none` |

Проверка после внесения (через 15–60 мин): `dig +short TXT dkim._domainkey.zvezditsa.ru` — должна вернуться строка выше
(reg.ru может разбить её на куски в кавычках — это нормально). Затем запросить код входа на свой ящик и в заголовках письма
увидеть `dkim=pass header.i=@zvezditsa.ru`.
