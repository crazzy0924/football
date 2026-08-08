#!/bin/bash
cd "d:/足球大模型1.0"
git add -A
git commit -F _msg.txt
git push origin master
rm _msg.txt _commit.py _commit.sh 2>/dev/null
echo "Done! All committed and pushed."
