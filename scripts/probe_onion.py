# -*- coding: utf-8 -*-
import re, sys

path = sys.argv[1]
data = open(path, "rb").read().decode("shift_jis", "replace")
print("len:", len(data))
m = re.search(r"<title>(.*?)</title>", data, re.DOTALL)
print("title:", m.group(1).strip()[:100] if m else "?")
for kw in ['<div class="thread"', 'class="post"', '<dt', '<dd', 'レス番号', 'ID:']:
    print(kw, "->", data.find(kw))
# 本文構造のサンプル
i = data.find("</h1>")
if i < 0:
    i = data.find("レス")
print("---- サンプル ----")
print(data[i:i+1800].replace("\n", " ")[:1800])
