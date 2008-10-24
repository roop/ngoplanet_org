#!/bin/sh
date > ngoplanet.log
echo "frontpage" >> ngoplanet.log
./rawdog-2.11/rawdog -d rawdog-config/ -c config --update --write --verbose 2>> ngoplanet.log
echo "bloglist" >> ngoplanet.log
./rawdog-2.11/rawdog -d rawdog-config/ -c bloglist/config --write --verbose 2>> ngoplanet.log
echo "summary" >> ngoplanet.log
./rawdog-2.11/rawdog -d rawdog-config/ -c summary/config --write --verbose 2>> ngoplanet.log
echo "rss" >> ngoplanet.log
./rawdog-2.11/rawdog -d rawdog-config/ -c rss/config --write --verbose 2>> ngoplanet.log
echo "opml" >> ngoplanet.log
./rawdog-2.11/rawdog -d rawdog-config/ -c opml/config --write --verbose 2>> ngoplanet.log
echo "DONE" >> ngoplanet.log
date >> ngoplanet.log
