import os
import json
import datetime
import re
import logging
import requests
import pandas as pd
from requests.adapters import HTTPAdapter, Retry

username = 'XXXXX'
password = 'XXXXX'

login_url = "https://awbw.amarriner.com/logincheck.php"
download_url = "https://awbw.amarriner.com/replay_download.php?games_id=%d"
game_url = "https://awbw.amarriner.com/2030.php?games_id=%d"
user_url = "https://awbw.amarriner.com/profile.php?username=%s"
user_games_url = "https://awbw.amarriner.com/gamescompleted.php?username=%s&type=%s"
user_replays_url = "https://awbw.amarriner.com/gamescompleted.php?start=%d&username=%s"
leaderboard_url = "https://awbw.amarriner.com/newleague_standings.php?type=%s&time=all"
default_save_path = '.'

def sanitize_username(username):
    return username.replace(' ', '%20')

def sanitize_fn(fn):
    return "".join(i for i in fn if i not in '"\/:*?<>|(),')

class AWBW():
    def __init__(self, username=username, password=password):
        self.session = requests.Session()
        retries = Retry(total=5, backoff_factor=2, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.login(username, password)
    
    def login(self, username, password):
        ret = self.session.post(login_url, data={'username':username, 'password':password})
        assert ret.content == b'1'
        
        
    def download_replay(self, replay_id, fn=None, path=default_save_path, game_data=None, overwrite=False):
        
        
        if fn is None:
            if game_data is not None:
                game_name = game_data['name']
                mtch = re.match('GL (STD|FOG|HF) \[T\d\]: %s vs %s' % (game_data['player1'], game_data['player2']), game_name)
                if mtch:
                    game_name = game_name.split(':')[0]
                else:
                    mtch = re.match('GL (STD|FOG|HF) \[T\d\]: %s vs %s' % (game_data['player2'], game_data['player1']), game_name)
                    if mtch:
                        game_name = game_name.split(':')[0]
                fn = '%d-%s-%s v %s-%s %s v %s' % (game_data['id'], game_name, game_data['player1'], game_data['player2'], game_data['map'], game_data['co1'], game_data['co2'])
            else:
                fn = str(replay_id)
        
        fn = sanitize_fn(fn)
        
        fn = os.path.join(path, fn + '.zip')
        
        if os.path.exists(fn) and not overwrite:
            return
        
        ret = self.session.get(download_url % replay_id)
        
        if ret.content == b'{"err":true,"message":"Game is not active, can not download"}':
            logging.warning("%d: Game is not active, can not download." % replay_id)
            return
            
        with open(fn, 'wb') as output_file:
            output_file.write(ret.content)
            
    def parse_game(self, game_id):
        ret = self.session.get(game_url % game_id)
        data = ret.content.decode(encoding='utf-8', errors='ignore')
        lines = data.split('\n')
        found = False
        for line in lines:
            if 'No game found with provided ID' in line:
                return -1, "No game found with provided ID."
            elif 'let playersInfo' in line:
                playersInfo = json.loads(line.split('= ')[-1].split(';\r')[0])
                found = True
                break
                
        if not found:
            return -1, lines
                
        player_ids = playersInfo.keys()
        if len(player_ids) != 2:
            return -1, "Invalid number of players."
        
        player1, player2 = [playersInfo[player_id]['users_username'] for player_id in player_ids]
        eliminated = [playersInfo[player_id]['players_eliminated'] for player_id in player_ids]
        if eliminated == ['N', 'Y']:
            winner = 1
        elif eliminated == ['Y', 'N']:
            winner = 2
        else:
            winner = -1
        
        for line in lines:
            if '<a href="prevmaps.php?maps_id=' in line:
                map_name = line.split('>')[-2].split('<')[0]
            elif 'const endData' in line:
                end_day = json.loads(line.split('endData = ')[1].split(';')[0])['day']
            elif '<a href="2030.php?games_id=' in line:
                game_name = line.split('>')[-2].split('<')[0]
                
        for line in lines:
            if 'let fogInfo =' in line:
                if line.split("=")[1][1] == "[":
                    fog = True
                elif line.split("=")[1][1:-1] == "null;":
                    fog = False
        
        co1, co2 = [playersInfo[player_id]['co_name'] for player_id in player_ids]
        
        return {'id':game_id, 'name':game_name, 'player1':player1, 'player2':player2, 'co1':co1, 'co2':co2, 'map':map_name, 'day':end_day, 'winner':winner, 'fog':fog}
    
    def get_available_user_replays(self, username, mode=None, path=None, day_limit=8):
        #Note, only 50 max of STD or FOG games (page limit)
        
        if path is None:
            path = os.path.join(default_save_path,  datetime.datetime.now().strftime("%Y_%m_%d"))
        if not os.path.exists(path):
            os.mkdir(path)
        
        if mode is None:
            self.get_available_user_replays(username, mode='std', path=path)
            self.get_available_user_replays(username, mode='fog', path=path)
            self.get_available_user_replays(username, mode='hf', path=path)
            return

        ret = self.session.get(user_games_url % (username, mode))
        data = ret.content.decode(encoding='utf-8', errors='ignore')
        lines = data.split('\n')
        for line in lines:
            if '<a class=norm2 href="2030.php?games_id=' in line:
                game_id = int(line.split("games_id=")[-1].split('&')[0])
                game_data = self.parse_game(game_id)
                if len(game_data) != 2:
                    if game_data['day'] < day_limit: continue
                    self.download_replay(game_id, path=path, game_data=game_data)
    
    def get_player_mmr(self, username):
        ret = self.session.get(user_url % sanitize_username(username))
        data = ret.content.decode(encoding='utf-8', errors='ignore')
        lines = data.split('\n')
        for line1, line2 in zip(lines[:-1], lines[1:]):
            if 'Official' in line1:
                return float(line2.split('>')[-1].split('&')[0])
        return -1, lines
    
    def parse_user_games(self, username):
        i = 1
        game_ids = []
        while True:
            ret = self.session.get(user_replays_url % (i, username))
            data = ret.content.decode(encoding='utf-8', errors='ignore')
            lines = data.split('\n')
            game_ids_ = []
            for line in lines:
                if ('<a class=norm href=2030.php?games_id=' in line):
                    game_id = int(line.split("=")[-1].split(">")[0])
                    game_ids_.append(game_id)
            if len(game_ids_) == 0:
                break
            else:
                game_ids += game_ids_
                i += len(game_ids_)
        game_infos = [self.parse_game(game_id) for game_id in game_ids]
        df = pd.DataFrame({key:[game_info[key] for game_info in game_infos] for key in game_infos[0].keys()})
        return df
    
    def get_leaderboard(self, mode='fog', rank_limit=100, rating_limit=1200):
        ret = self.session.get(leaderboard_url % mode)
        data = ret.content.decode(encoding='utf-8', errors='ignore')
        lines = data.split('\n')
        leaders = []
        for line1, line2, line3 in zip(lines[:-2], lines[1:-1], lines[2:]):
            if ('<td style="padding-right' in line2):
                rank = int(line1.split('>')[-2].split('.')[0])
                username = line2.split("username=")[1].split('"')[0]
                rating = float(line3.split('>')[-2].split('<')[0])
                if (rating < rating_limit) or (rank > rank_limit):
                    break
                leaders.append([rank, username, rating])

        return leaders
    
    def save_leaderboard_replays(self, mode='fog', rank_limit=100, rating_limit=1200, path=None):
        
        if path is None:
            path = os.path.join(default_save_path,  datetime.datetime.now().strftime("%Y_%m_%d"))
        if not os.path.exists(path):
            os.mkdir(path)
            
        for rank, username, rating in self.get_leaderboard(mode=mode, rank_limit=rank_limit, rating_limit=rating_limit):
            print(rank, username, rating)
            self.get_available_user_replays(username, path=path)
