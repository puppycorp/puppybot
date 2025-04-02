import type { MsgFromBot, MsgToBot } from "./types"

export const encodeBotMsg = (msg: MsgToBot): Buffer => {
	const buffer = Buffer.alloc(4 + msg.length)
	buffer.writeUInt32BE(msg.length, 0)
	buffer.write(msg, 4)
	return buffer
}

export const decodeBotMsg = (buffer: Buffer): MsgFromBot => {
	
}