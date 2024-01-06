from linebot import (LineBotApi, WebhookHandler)
from linebot.exceptions import (LineBotApiError, InvalidSignatureError)
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, SourceUser, SourceGroup, SourceRoom, TemplateSendMessage, ConfirmTemplate, MessageAction, ButtonsTemplate, 
    ImageCarouselTemplate, ImageCarouselColumn, URIAction, PostbackAction, DatetimePickerAction, CameraAction, CameraRollAction, LocationAction, CarouselTemplate, CarouselColumn, 
    PostbackEvent, StickerMessage, StickerSendMessage, LocationMessage, LocationSendMessage, ImageMessage, VideoMessage, AudioMessage, FileMessage, UnfollowEvent, FollowEvent, 
    JoinEvent, LeaveEvent, BeaconEvent, MemberJoinedEvent, MemberLeftEvent, FlexSendMessage, BubbleContainer, ImageComponent, BoxComponent, TextComponent, SpacerComponent, 
    IconComponent, ButtonComponent, SeparatorComponent, QuickReply, QuickReplyButton, ImageSendMessage)
import requests, traceback, logging, boto3, json, sys, os
from botocore.exceptions import ClientError
from bs4 import BeautifulSoup
import psycopg2

## User ##
SQL_CREATE_USER_TABLE="CREATE TABLE users (line_id varchar PRIMARY KEY, school_id integer, name varchar);"
SQL_INSERT_USER="INSERT INTO users (line_id, school_id, name) VALUES (%s, %s, %s)"
SQL_GET_USERS="SELECT * FROM users where line_id = %s"

## Room ##
SQL_CREATE_ROOM_TABLE="CREATE TABLE room (name varchar PRIMARY KEY, category varchar);"
SQL_INSERT_ROOM="INSERT INTO room (name, category) VALUES (%s, %s)"

## Borrow ##
SQL_CREATE_BORROW_TABLE="CREATE TABLE borrow (id serial, user_id varchar, room_name varchar, register_date date, register_time char, PRIMARY KEY (user_id, register_date, register_time), FOREIGN KEY (user_id) REFERENCES users(line_id), FOREIGN KEY (room_name) REFERENCES room(name));"
SQL_GET_USER_BORROW="SELECT * FROM borrow WHERE user_id=%s"
SQL_BORROW="INSERT INTO borrow (user_id, room_name, register_date, register_time) VALUES (%s, %s, %s, %s)";
SQL_GET_AVAILABLE="SELECT time_slot FROM ( VALUES ('a'), ('b'), ('c'), ('d'), ('e'), ('f'), ('g'), ('h') ) AS all_time_slots (time_slot) WHERE NOT EXISTS ( SELECT 1 FROM borrow WHERE room_name = %s AND register_date = %s AND register_time = all_time_slots.time_slot);"

## Cancel ##
SQL_CANCEL="DELETE FROM borrow WHERE id = %s AND user_id=%s";

## Mode ##
SQL_CREATE_RESERVE_MODE="CREATE TABLE reserve_mode (user_id varchar PRIMARY KEY, FOREIGN KEY (user_id) REFERENCES users(line_id));"
SQL_CREATE_SEARCH_MODE="CREATE TABLE search_mode (user_id varchar PRIMARY KEY, FOREIGN KEY (user_id) REFERENCES users(line_id));"
SQL_CREATE_CANCEL_MODE="CREATE TABLE cancel_mode (user_id varchar PRIMARY KEY, FOREIGN KEY (user_id) REFERENCES users(line_id));"
SQL_TO_RESERVE="INSERT INTO reserve_mode (user_id) VALUES (%s)";
SQL_TO_SEARCH="INSERT INTO search_mode (user_id) VALUES (%s)";
SQL_TO_CANCEL="INSERT INTO cancel_mode (user_id) VALUES (%s)";
SQL_NOT_TO_RESERVE="DELETE FROM reserve_mode WHERE user_id = %s"
SQL_NOT_TO_SEARCH="DELETE FROM search_mode WHERE user_id = %s"
SQL_NOT_TO_CANCEL="DELETE FROM cancel_mode WHERE user_id = %s"
SQL_FIND_RESERVE_MODE="SELECT * FROM reserve_mode WHERE user_id = %s"
SQL_FIND_SEARCH_MODE="SELECT * FROM search_mode WHERE user_id = %s"
SQL_FIND_CANCEL_MODE="SELECT * FROM cancel_mode WHERE user_id = %s"

## Target ##
SQL_CREATE_TARGET_ROOM_TABLE="CREATE TABLE target_room (line_id varchar PRIMARY KEY, room_name varchar);"
SQL_CREATE_TARGET_DATE_TABLE="CREATE TABLE target_date (line_id varchar PRIMARY KEY, reserve_date date);"
SQL_FIND_TARGET_ROOM = "SELECT room_name FROM target_room WHERE line_id = %s"
SQL_FIND_TARGET_DATE = "SELECT reserve_date FROM target_date WHERE line_id = %s"
SQL_INSERT_TARGET_ROOM = "INSERT INTO target_room (line_id, room_name) VALUES (%s, %s)"
SQL_INSERT_TARGET_DATE = "INSERT INTO target_date (line_id, reserve_date) VALUES (%s, %s)"
SQL_DELETE_TARGET_ROOM = "DELETE FROM target_room WHERE line_id = %s"
SQL_DELETE_TARGET_DATE = "DELETE FROM target_date WHERE line_id = %s"

def runSql(conn, QUERY, param):
    res = "success"
    cur = conn.cursor()
    cur.execute(QUERY, param)
    if QUERY.split()[0] == "SELECT":
        res = cur.fetchall()
    conn.commit()
    cur.close()
    return res

# === 將這個 Lambda 設定的環境變數 (environment variable) 輸出作為參考 ] ===
logger = logging.getLogger()
logger.setLevel(logging.INFO) 
channel_secret = os.getenv('LINE_CHANNEL_SECRET', None)
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', None)
if not channel_secret or not channel_access_token:
    logger.error('需要在 Lambda 的環境變數 (Environment variables) 裡新增 LINE_CHANNEL_SECRET 和 LINE_CHANNEL_ACCESS_TOKEN 作為環境變數。')
    sys.exit(1)
line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)    
logger.info(os.environ)  

# ===[ 定義你的函式 ] ===
def get_userOperations(userId):
    return None

# === [ 定義回覆使用者輸入的文字訊息 - 依據使用者狀態，回傳組成 LINE 的 Template 元素 ] ===
def compose_textReplyMessage(userId, userOperations, messageText):
    return TextSendMessage(text='好的！已收到您的文字 %s！' % messageText)

# === [ 定義回覆使用者與程式使用者界面互動時回傳結果後的訊息 - 依據使用者狀態，回傳組成 LINE 的 Template 元素 ] ===
def compose_postbackReplyMessage(userId, userOperations, messageData):
    return TextSendMessage(text=messageData)

def lambda_handler(event, context):
    conn = psycopg2.connect(host='database-2.ca2afvzggncm.us-east-1.rds.amazonaws.com', port='5432', dbname='', user='postgres', password='xxxxx')
    
    timeslot_map = {
      "a": "08:00-09:00",
      "b": "09:00-10:00",
      "c": "10:00-11:00",
      "d": "11:00-12:00",
      "e": "12:00-13:00",
      "f": "13:00-14:00",
      "g": "14:00-15:00",
      "h": "15:00-16:00"
    }
    
    @handler.add(MessageEvent, message=TextMessage)    
    def handle_text_message(event):
        
        userId = event.source.user_id
        messageText = event.message.text
        tk = event.reply_token
        userOperations = get_userOperations(userId)
        logger.info('收到 MessageEvent 事件 | 使用者 %s 輸入了 [%s] 內容' % (userId, messageText))
        
        if messageText[0] != '@':
            #line_bot_api.reply_message(userId,TextSendMessage(messageText))
            if len(messageText) < 10:
                msg = 'Your format is incorrect.'
                line_bot_api.reply_message(tk,TextSendMessage(msg))  # 回傳訊息
            else:
                check = 0
                msg = 'Your format is incorrect.'
                for i in range (9):
                    if messageText[i] < '0' or messageText[i] > '9':
                        line_bot_api.reply_message(tk, TextSendMessage(msg))  # 回傳訊息
                        check = 1
                        break
                if check != 1:
                    if messageText[9] >= '0' and messageText[9] <= '9':
                        msg = 'Your format is incorrect.'
                        line_bot_api.reply_message(tk, TextSendMessage(msg))  # 回傳訊息
                    else:
                        ID = messageText[:9]
                        name = messageText[9:]
                        runSql(conn, SQL_INSERT_USER, [userId, ID, name])
                        line_bot_api.reply_message(tk, TextSendMessage('恭喜!您已成功註冊')) 
                        
        elif messageText == '@reserve' or messageText == '@search':
            check = 1
            if messageText == '@reserve':
                # check if the userId is registered in the database
                res = runSql(conn, SQL_GET_USERS, [userId])
                if len(res) == 0:
                    check = 0
                    line_bot_api.reply_message(tk, TextSendMessage('你尚未註冊。請輸入您的學號與真名(不要空格)')) 
                runSql(conn, SQL_NOT_TO_SEARCH, [userId])
                runSql(conn, SQL_NOT_TO_CANCEL, [userId])
                runSql(conn, SQL_TO_RESERVE, [userId])
            else:
                runSql(conn, SQL_NOT_TO_RESERVE, [userId])
                runSql(conn, SQL_NOT_TO_CANCEL, [userId])
                runSql(conn, SQL_TO_SEARCH, [userId])
            
            if check:
                line_bot_api.push_message(userId, TemplateSendMessage(
                    alt_text='ButtonsTemplate',
                    template=ButtonsTemplate(
                      thumbnail_image_url='https://www.wowlavie.com/files/article/a1/17851/atl_m_200017851_425.jpeg',
                      title='Category',
                      text='please choose the type of the room',
                      actions=[
                        MessageAction(
                          label='AUDIO-VISUAL ROOM',
                          text='@AUDIO-VISUAL ROOM'
                        ),
                        MessageAction(
                          label='MEETING ROOM',
                          text='@MEETING ROOM'
                        ),
                        MessageAction(
                          label='DANCING ROOM',
                          text='@DANCING ROOM'
                        ),
                        MessageAction(
                          label='KITCHEN',
                          text='@KITCHEN'
                        ),
                      ]
                    )
                  ))
                  
        elif messageText == '@cancel':
            runSql(conn, SQL_NOT_TO_RESERVE, [userId])
            runSql(conn, SQL_NOT_TO_SEARCH, [userId])
            cancel_mode = runSql(conn, SQL_FIND_CANCEL_MODE, [userId])
            if len(cancel_mode) == 0:
                runSql(conn, SQL_TO_CANCEL, [userId])
            records = runSql(conn, SQL_GET_USER_BORROW, [userId])
            cancel_opt_msg = 'Choose one record to cancel:\n'
            for r in records:
                cancel_opt_msg = cancel_opt_msg + 'number ' + str(r[0]) + ':\n' + str(r[2]) + '\n' + str(r[3]) + ' ' + str(timeslot_map[r[4]]) + '\n\n'
            cancel_opt_msg  = cancel_opt_msg + 'Please select the number of the record, e.g. @1'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(cancel_opt_msg))
              
        elif messageText == '@AUDIO-VISUAL ROOM':
            reserve_mode = runSql(conn, SQL_FIND_RESERVE_MODE, [userId])
            search_mode = runSql(conn, SQL_FIND_SEARCH_MODE, [userId])
            if len(reserve_mode) == 0 and len(search_mode) == 0:
                line_bot_api.reply_message(event.reply_token, TextSendMessage('Please select reserve or search mode.'))
            else:
                line_bot_api.push_message(userId, TemplateSendMessage(
                  alt_text='ButtonsTemplate',
                  template=ButtonsTemplate(
                    thumbnail_image_url='https://www.wowlavie.com/files/article/a1/17851/atl_m_200017851_425.jpeg',
                    title='Audio-Visual Room Reservation',
                    text='please choose the room',
                    actions=[
                      MessageAction(
                        label='NARRATOR',
                        text='@NARRATOR'
                      ),
                      MessageAction(
                        label='TYLER',
                        text='@TYLER'
                      ),
                    ]
                  )
                ))
            
        elif messageText == '@MEETING ROOM':
            reserve_mode = runSql(conn, SQL_FIND_RESERVE_MODE, [userId])
            search_mode = runSql(conn, SQL_FIND_SEARCH_MODE, [userId])
            if len(reserve_mode) == 0 and len(search_mode) == 0:
                line_bot_api.reply_message(event.reply_token, TextSendMessage('Please select reserve or search mode.'))
            else:
                line_bot_api.push_message(userId, TemplateSendMessage(
                  alt_text='ButtonsTemplate',
                  template=ButtonsTemplate(
                    thumbnail_image_url='https://www.wowlavie.com/files/article/a1/17851/atl_m_200017851_425.jpeg',
                    title='Meeting Room Reservation',
                    text='please choose the room',
                    actions=[
                      MessageAction(
                        label='MOJITO',
                        text='@MOJITO'
                      ),
                      MessageAction(
                        label='GIMLET',
                        text='@GIMLET'
                      ),
                      MessageAction(
                        label='NEGRONI',
                        text='@NEGRONI'
                      ),
                      MessageAction(
                        label='MARTINI',
                        text='@MARTINI'
                      ),
                    ]
                  )
                ))
            
        elif messageText == '@MOJITO' or messageText == '@GIMLET' or messageText == '@NEGRONI' or messageText == '@MARTINI' or messageText == '@NARRATOR' or messageText == '@TYLER' or messageText == '@DANCING ROOM' or messageText == '@KITCHEN':
            reserve_mode = runSql(conn, SQL_FIND_RESERVE_MODE, [userId])
            search_mode = runSql(conn, SQL_FIND_SEARCH_MODE, [userId])
            if len(reserve_mode) == 0 and len(search_mode) == 0:
                line_bot_api.reply_message(event.reply_token, TextSendMessage('Please select reserve or search mode.'))
            else:
                line_bot_api.push_message(userId, TemplateSendMessage(
                  alt_text='ButtonsTemplate',
                  template=ButtonsTemplate(
                    thumbnail_image_url='https://megapx-assets.dcard.tw/images/c2fa8fe9-9a35-4fa7-86d7-c0e6e9e25ed9/1280.webp',
                    title='time table',
                    text='Please choose the date',
                    actions=[
                      DatetimePickerAction(
                        label='Date',
                        data='action=buy&itemid=1',
                        mode='date',
                        initial='2024-01-06',
                        min='2024-01-06',
                        max='2024-02-06'
                      )
                    ]
                  )
                ))
                runSql(conn, SQL_DELETE_TARGET_ROOM, [userId])
                runSql(conn, SQL_DELETE_TARGET_DATE, [userId])
                runSql(conn, SQL_INSERT_TARGET_ROOM, [userId, messageText[1:]])
            
        elif messageText[1] in ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] and len(messageText) == 2:
            room = runSql(conn, SQL_FIND_TARGET_ROOM, [userId])
            date = runSql(conn, SQL_FIND_TARGET_DATE, [userId])
            res = runSql(conn, SQL_GET_AVAILABLE, [room[0][0], date[0][0]])
            available_flag = 0
            for time in res:
                if time[0] == messageText[1]:
                    available_flag = 1
                    break
            if available_flag==0 :
                line_bot_api.reply_message(event.reply_token, TextSendMessage("This time period has already been reserved."))
            else:
                runSql(conn, SQL_BORROW, [userId, room[0][0], date[0][0], messageText[1]])
                runSql(conn, SQL_DELETE_TARGET_ROOM, [userId])
                runSql(conn, SQL_DELETE_TARGET_DATE, [userId])
                success_msg = 'Successfully reserved\n' + str(room[0][0]) + '\non ' + str(date[0][0]) + ' ' + str(timeslot_map[messageText[1]])
                runSql(conn, SQL_NOT_TO_RESERVE, [userId])
                line_bot_api.reply_message(event.reply_token, TextSendMessage(success_msg)) 
                
        elif messageText[1] in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']:
            cancel_mode = runSql(conn, SQL_FIND_CANCEL_MODE, [userId])
            if len(cancel_mode) == 0:
                line_bot_api.reply_message(event.reply_token, TextSendMessage('Please select cancel mode first to cancel.'))
            else:
                cancel_number = 0
                for i in range(1, int(len(messageText))):
                    if messageText[i] in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'] :
                        cancel_number = cancel_number * 10 + int(messageText[i])
                    else:
                        line_bot_api.reply_message(tk, TextSendMessage('Your format is incorrect'))
                        break
                records = runSql(conn, SQL_GET_USER_BORROW, [userId])
                all_numbers = []
                for r in records:
                    all_numbers.append(int(r[0]))
                if cancel_number in all_numbers:
                    # cancel the record with cancel_number
                    runSql(conn, SQL_CANCEL, [cancel_number, userId])
                    runSql(conn, SQL_NOT_TO_CANCEL, [userId])
                    line_bot_api.reply_message(event.reply_token, TextSendMessage('Successfully cancelled'))
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage('Invalid number. Please input one of the number from above.'))
            
        else:
            line_bot_api.reply_message(tk, TextSendMessage('Your format is incorrect'))  # 回傳訊息

    # ==== [ 處理使用者按下相關按鈕回應後的後續動作 PostbackEvent 程式區段 ] ===
    @handler.add(PostbackEvent)   
    def handle_postback(event):
        userId = event.source.user_id 
        messageData = event.postback.params['date']
        userOperations = get_userOperations(userId)
        logger.info('收到 PostbackEvent 事件 | 使用者 %s' % userId)
        runSql(conn, SQL_DELETE_TARGET_DATE, [userId])
        reserve_mode = runSql(conn, SQL_FIND_RESERVE_MODE, [userId])
        search_mode = runSql(conn, SQL_FIND_SEARCH_MODE, [userId])
        if len(reserve_mode) == 0 and len(search_mode) == 0:
            line_bot_api.reply_message(event.reply_token, TextSendMessage('Please select reserve or search mode.'))
        room = runSql(conn, SQL_FIND_TARGET_ROOM, [userId])
        if len(room) == 0:
            line_bot_api.reply_message(event.reply_token, TextSendMessage('No room is specified. Please select room first.'))
        else:
            runSql(conn, SQL_INSERT_TARGET_DATE, [userId, messageData])
            timeslot = runSql(conn, SQL_GET_AVAILABLE, [room[0][0], messageData])
            time_msg = 'The available time slots are:\n'
            for time in timeslot:
                time_msg = time_msg + time[0] + ': '+ timeslot_map[time[0]] + '\n'
            if len(search_mode) == 0:
                time_msg = time_msg + 'Please input @timeslot, e.g. @a'
            else:
                runSql(conn, SQL_DELETE_TARGET_DATE, [userId])
                runSql(conn, SQL_DELETE_TARGET_ROOM, [userId])
                runSql(conn, SQL_NOT_TO_SEARCH, [userId])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(time_msg)) 
        
    # ==== [ 處理追縱 FollowEvent 的程式區段 ] === 
    @handler.add(FollowEvent)  
    def handle_follow(event):
        userId = event.source.user_id
        logger.info('收到 FollowEvent 事件 | 使用者 %s' % userId)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text='歡迎您的加入!'))      

# === [ 這裡才是 lambda_handler 主程式 ]===================================================================================== 
    try:
        signature = event['headers']['x-line-signature']  # === 取得 event (事件) x-line-signature 標頭值 (header value)
        body = event['body']  # === 取得事件本文內容(body)
        # eventheadershost = event['headers']['host']        
        handler.handle(body, signature)  # === 處理 webhook 事件本文內容(body)
    
    # === [ 發生錯誤的簽章內容(InvalidSignatureError)的程式區段 ] ===
    except InvalidSignatureError:
        return {
            'statusCode': 400,
            'body': json.dumps('InvalidSignature') }        
    
    # === [ 發生錯誤的LineBotApi內容(LineBotApiError)的程式區段 ] ===
    except LineBotApiError as e:
        logger.error('呼叫 LINE Messaging API 時發生意外錯誤: %s' % e.message)
        for m in e.error.details:
            logger.error('-- %s: %s' % (m.property, m.message))
        return {
            'statusCode': 400,
            'body': json.dumps(traceback.format_exc()) }
    
    # === [ 沒有錯誤(回應200 OK)的程式區段 ] ===
    return {
        'statusCode': 200,
        'body': json.dumps('OK') }