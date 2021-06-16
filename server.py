from asyncio.tasks import ensure_future
import json
from aiohttp import web, ClientSession, WSMsgType, client_exceptions
from aiortc import (
    RTCPeerConnection,
    RTCIceCandidate,
    RTCSessionDescription,
    MediaStreamTrack,
    sdp
)
from aiortc.rtcconfiguration import RTCConfiguration, RTCIceServer
from asyncio.exceptions import CancelledError
from av import VideoFrame
import argparse
import ssl
import logging
import cv2, os, base64
from io import BytesIO
import time
from flask.globals import session

logger = logging.getLogger("pc")
ws = None
pc = None
ROOT = os.path.dirname(__file__)
logger = logging.getLogger("pc")
channel = None
session = None

connections = {}


class FrameGrabber(MediaStreamTrack):
    kind = "video"
    
    def __init__(self, track):
        super().__init__()  # don't forget this!
        self.track = track
        self._count = 0
        # self.face_cascade = cv2.CascadeClassifier(
        #     os.path.join(ROOT, "res/haarcascade_frontalface_default.xml")
        # )

    def draw_face_detections(self, frame):
        cvImg = frame.to_ndarray(format="rgb24")
        grayImg = cv2.cvtColor(cvImg, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(grayImg, 1.1, 4)
        for (x, y, w, h) in faces:
            cv2.rectangle(cvImg, (x, y), (x + w, y + h), (255, 0, 0), 2)
        return cvImg

    async def recv(self):
        frame = await self.track.recv()
        try:
            if self._count < 350:
                print("Count: ", self._count)
                ensure_future(self.getData(frame))
            self._count += 1;
        except CancelledError as e:
            print("The Task carry out the request failed: ", e.args)
        except client_exceptions.ClientConnectorError as cce:
            print("Cannot connect to remote client: ",cce.strerror)
        return frame

    async def getData(self, frame):
        base64Str = self.convert_frame_to_base64(frame)
        result = await self.fetchVitalsData(base64Str)
        # print("Result ====> ")
        # print(result)
        await ws.send_json({"type":"result", "result": result})
        

    def convert_frame_to_base64(self,frame: VideoFrame):
        img = frame.to_image()
        output_buffer = BytesIO()
        img.save(output_buffer, format="JPEG")
        binary_data = output_buffer.getvalue()
        base64_str = base64.b64encode(binary_data)
        return base64_str


    async def fetchVitalsData(self,imgStr):
        print("sending request with image string: ", imgStr[0:15])
        reqBody = {
            "id": 1,
            "name": "something",
            "pms": "uk",
            "status": 1,
            "photo": imgStr.decode("utf-8"),
        }
        async with session.post("http://15.207.11.162:8500/data/uploadPhoto", json=reqBody) as resp:
            if resp.ok:
                smtg = await resp.text("utf8")
                # print("response body: ", smtg)
                return smtg
            print("Request error from api %d".format(resp.status))
            return "Request error from api %d".format(resp.status)

def log_info(msgType, msg):
    print(">>>>",time.strftime("%D-%H:%M:%S"),"  ", msgType," =>", msg)


async def handle_offer(peer: RTCPeerConnection,osdp, otype):
    offer = RTCSessionDescription(osdp, otype)
    await peer.setRemoteDescription(offer)
    answer = await peer.createAnswer()
    await peer.setLocalDescription(answer)
    await ws.send_json({"type": answer.type, "sdp": answer.sdp})
    

def candidate_from_req(iceCandidate):
    bits = iceCandidate["candidate"].split()
    print("Bits: ", bits)
    assert len(bits) >= 8
    candidate = RTCIceCandidate(
        component=int(bits[1]),
        foundation=bits[0].split(":")[1],
        ip=bits[4],
        port=int(bits[5]),
        priority=int(bits[3]),
        protocol=bits[2],
        type=bits[7],
        sdpMid=iceCandidate["sdpMid"],
        sdpMLineIndex=iceCandidate["sdpMLineIndex"]
    )
    for i in range(8, len(bits) - 1, 2):
        if bits[i] == "raddr":
            candidate.relatedAddress = bits[i + 1]
        elif bits[i] == "rport":
            candidate.relatedPort = int(bits[i + 1])
        elif bits[i] == "tcptype":
            candidate.tcpType = bits[i + 1]
    return candidate

def candidate_to_req(cand:RTCIceCandidate):
    bits = "candidate"
    bits += cand.foundation
    bits += cand.component
    bits += cand.priority
    bits += cand.ip
    bits += cand.port
    bits += "typ"
    bits += cand.type
    for i in range(3):
        if cand.relatedAddress:
            bits += "raddr "+cand.relatedAddress
        elif cand.relatedPort:
            bits += "rport "+cand.relatedPort
        elif cand.tcpType:
            bits += "tcptype " + cand.tcpType
    iceCand = {"candidate": bits, "sdpMid": cand.sdpMid, "sdpMLineIndex":cand.sdpMLineIndex}
    return iceCand

async def handle_ice(peer: RTCPeerConnection, cand):
    candidate = candidate_from_req(cand)
    # RTCIceCandidate()
    print("ICE Candidate", candidate.sdpMLineIndex)
    await peer.addIceCandidate(candidate)
    # ice_candidate = sdp.candidate_from_sdp(peer.localDescription.sdp);
    # iceCand = candidate_to_req(ice_candidate);
    # ws.send_json({"type": "iceCandidate", "IceCandidate": iceCand})

async def wsHandler(req):
    global ws,pc, session, connections
    origin =  req.headers["Origin"]
    if origin in connections.keys():
        print("Reusing the existing connetion for: ", origin)
        # await connections[origin].close()
        # ws=connections[origin]
        return
    else:
        print("Creating the new connection for: ",origin)
        ws = web.WebSocketResponse()
        connections[origin] = ws
    
    if  not ws.prepared:
        print("Preparing the connection for ", origin)
        await ws.prepare(req)
    print("Connections existing are: ",connections)
    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            if msg.data == "close":
                await ws.close()
            elif msg.data == "open":
                print("web socket opened ", msg.type)
            else:
                body = msg.json();
                print("Message: \n", body)
                if body["Msgtype"] == "offer":
                    config = RTCConfiguration([RTCIceServer("stun:stun.l.google.com:19302"), RTCIceServer('turn:numb.viagenie.ca',username="webrtc@live.com", credential='muazkh',)])
                    pc = RTCPeerConnection(config)
                    session = ClientSession()
                    
                    @pc.on("track")
                    def on_track(track):
                        print("Got track...")
                        if track.kind == "video":
                            localStream = FrameGrabber(track)
                            pc.addTrack(localStream)
                    
                    @pc.on("stream")
                    def on_stream(stream):
                        print("Got stream...")
                    
                    await handle_offer(pc, body["sdp"], body["Msgtype"]);
                if body["Msgtype"] == "ice" and pc is not None:
                    # print("Ice is: ", body["IceCandidate"])
                    await handle_ice(pc, body["IceCandidate"]);
        
        elif msg.type == WSMsgType.ERROR:
            print("ws connection closed with exception %s" % ws.exception())
    print("Closing the websocket for: ", origin)
    connections.pop(origin)
    return ws


async def on_shutdown(app):
    if session is not None:
        print("Closing the request session...")
        await session.close()
    print("closing...")
    await ws.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="WebRTC audio / video / data-channels demo"
    )
    parser.add_argument("--cert-file", help="SSL certificate file (for HTTPS)")
    parser.add_argument("--key-file", help="SSL key file (for HTTPS)")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host for HTTP server (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Port for HTTP server (default: 8080)"
    )
    parser.add_argument("--record-to", help="Write received media to a file."),
    parser.add_argument("--verbose", "-v", action="count")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.cert_file:
        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(args.cert_file, args.key_file)
    else:
        ssl_context = None

    app = web.Application()
    app.on_shutdown.append(on_shutdown)
    app.router.add_get("/ws", wsHandler)
    web.run_app(app, access_log=None, host=args.host,
                port=args.port, ssl_context=ssl_context, )
