#!/bin/sh
date
echo "frontpage"
./rawdog-2.11/rawdog -d rawdog-config/ -c config --update --write --verbose
echo "bloglist"
./rawdog-2.11/rawdog -d rawdog-config/ -c bloglist/config --write --verbose
echo "summary"
./rawdog-2.11/rawdog -d rawdog-config/ -c summary/config --write --verbose
echo "rss"
./rawdog-2.11/rawdog -d rawdog-config/ -c rss/config --write --verbose
echo "opml"
./rawdog-2.11/rawdog -d rawdog-config/ -c opml/config --write --verbose
echo "DONE"
date
