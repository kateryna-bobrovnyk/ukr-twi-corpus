import gzip
import json
import pickle
import re
import time

from requests_html import HTMLSession, HTML
from datetime import datetime

session = HTMLSession()

class Bag(): 
    def __init__(self, start): 
        self.__item = start 
    def get(self): 
        return self.__item 
    def put(self, new_value): 
        self.__item = new_value

REQUEST_PAUSE = 2 #seconds

def cached_get(url, max_pos, headers, cache, last_network_request_time):
    u = url if max_pos is None else url + '&max_position={}'.format(max_pos)
    #print("Url: {}".format(u))            
    key = (u, frozenset(headers.items()))
    if key in cache:
        return json.loads(gzip.decompress(cache[key]))
    else:
        last_req_time = last_network_request_time.get()
        current_time  = time.monotonic()
        diff          = abs(current_time - last_req_time)
        if diff < REQUEST_PAUSE:
            #print("Sleeping for {}".format(REQUEST_PAUSE - diff))
            time.sleep(REQUEST_PAUSE - diff)
        #params        = {'max_position': max_pos} if max_pos is not None else None
        res           = session.get(u, headers = headers) # params = params,
        rj            = res.json()
        cache[key]    = gzip.compress(bytes(json.dumps(rj), 'utf-8'), 9)
        last_network_request_time.put(time.monotonic())
        return rj

def save_url_cache(cache, dest_path):
    assert type(cache) is dict, "Url cache must be a dictionary, but got {}".format(type(cache))
    with open(dest_path, "wb") as f:
        pickle.dump(cache, f)

def load_url_cache(source_path):
    with open(source_path, "rb") as f:
        res = pickle.load(f)
        assert type(res) is dict, "Url cache must be a dictionary, but got {}".format(type(res))
        return res

def get_tweets_search(user, cache, last_network_request_time, pages):
    """Gets tweets for a given user, via the Twitter frontend API."""

    INIT_URL = f'https://twitter.com/search?f=tweets&vertical=default&q=from%3A{user}&src=typd'
    RELOAD_URL = \
        f'https://twitter.com/i/search/timeline?f=tweets&vertical=default&include_available_features=1&include_entities=1&reset_error_state=false&src=typd&q=from%3A{user}'
    
    headers = {
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': f'https://twitter.com/{user}',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/603.3.8 (KHTML, like Gecko) Version/10.1.2 Safari/603.3.8',
        'X-Twitter-Active-User': 'yes',
        'X-Requested-With': 'XMLHttpRequest'
    }

    comma = ","
    dot   = "."

    def mkInt(s):
        return int(s.split(" ")[0].replace(comma, "").replace(dot, ""))

    def gen_tweets(pages):
       
        #print("Downloading {}".format(INIT_URL))
        seen_tweets = set()
        r = cached_get(RELOAD_URL, None, headers, cache, last_network_request_time)

        while pages > 0:
            #print("r = {}".format(r.text))
            rj = r
            #print("JSON: {}".format(str(j)[:100]))
            h = rj['items_html'].strip()
            if len(h) == 0:
                break
            have_more_items = rj['has_more_items']
            html = HTML(html = h, url = 'bunk', default_encoding = 'utf-8')
            
            tweets = []
            try:
                tweets_stream = html.find('.stream-item')
            except Exception as e:
                raise RuntimeError(".stream-item not found! {}".format(e))
            for tweet_node in tweets_stream:
                try:
                    tweet_container_node_raw = tweet_node.find('.tweet')
                    if not tweet_container_node_raw:
                        continue
                    tweet_container_node = tweet_container_node_raw[0]    
                    original_author = tweet_container_node.attrs['data-screen-name']

                    text_raw = tweet_container_node.find('.tweet-text')
                    if not text_raw:
                        continue
                        #raise RuntimeError("Invalid raw text value {} of tweet:\ntweet: {}\ntext: {}".format(text_raw, tweet_container_node.html))
                    text_raw_node = text_raw[0]

                    text    = text_raw_node.full_text
                    lang    = text_raw_node.attrs['lang']
                    #tweetId = tweet_container_node.find('.js-permalink')[0].attrs['data-conversation-id']
                    time    = datetime.fromtimestamp(int(tweet_container_node.find('._timestamp')[0].attrs['data-time-ms'])/1000.0)

                    interactions = [x.text for x in tweet_container_node.find('.ProfileTweet-actionCount')]

                    replies  = mkInt(interactions[0])
                    retweets = mkInt(interactions[1])
                    likes    = mkInt(interactions[2])
                    hashtags = [hashtag_node.full_text for hashtag_node in tweet_container_node.find('.twitter-hashtag')]
                    urls     = \
                        [ url_node.attrs['data-expanded-url']
                          for url_node in tweet_container_node.find('a.twitter-timeline-link:not(.u-hidden)')
                          if 'data-expanded-url' in url_node.attrs ]
                    key = (tweetId, time, text)
                    if key not in seen_tweets:
                        seen_tweets.add(key)

                        yield \
                            { #'tweetId': tweetId
                              'time': time
                            , 'lang': lang
                            , 'text': text
                            , 'replies': replies
                            , 'retweets': retweets
                            , 'likes': likes
                            , 'hashtags': hashtags
                            , 'urls': urls
                            , 'author': original_author
                            #, 'raw': text_raw
                            #, 'html': tweet_node.html
                            }
                except Exception as e:
                    raise RuntimeError("Got error while processing tweet:\n{}\nError: {}".format(tweet_container_node, e))

            if 'min_position' in rj:
                last_tweet = rj['min_position']
            else:
                last_tweet = tweets_stream[-1].attrs['data-item-id']

            if have_more_items:
                #print("Downloading {}, last_tweet = {}".format(RELOAD_URL, last_tweet))
                r = cached_get(RELOAD_URL, last_tweet, headers, cache, last_network_request_time)
                pages += -1
            else:
                break

    yield from gen_tweets(pages)
