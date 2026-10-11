// Decode actual Chromium PNG captures, retaining a small colour-quantization
// tolerance. Encoded byte changes alone are not visible gameplay changes.
import { inflateSync } from 'node:zlib';

function pixels(data) {
  if (!data.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) throw new Error('Invalid screenshot PNG');
  let width, height, channels, position = 8;
  const compressed = [];
  while (position + 12 <= data.length) {
    const length = data.readUInt32BE(position), type = data.toString('ascii', position + 4, position + 8);
    if (position + length + 12 > data.length) throw new Error('Truncated screenshot PNG');
    const chunk = data.subarray(position + 8, position + length + 8);
    if (type === 'IHDR') {
      if (length !== 13 || chunk[8] !== 8 || ![2,6].includes(chunk[9]) || chunk[10] || chunk[11] || chunk[12]) throw new Error('Unsupported screenshot PNG encoding');
      width = chunk.readUInt32BE(0); height = chunk.readUInt32BE(4); channels = chunk[9] === 6 ? 4 : 3;
      if (!width || !height || width * height > 10_000_000) throw new Error('Screenshot geometry exceeds bound');
    }
    if (type === 'IDAT') compressed.push(chunk);
    position += length + 12;
  }
  if (!width || !compressed.length) throw new Error('Missing screenshot pixels');
  const stride = width * channels, raw = inflateSync(Buffer.concat(compressed), {maxOutputLength: (stride + 1) * height});
  if (raw.length !== (stride + 1) * height) throw new Error('Screenshot pixel size mismatch');
  const output = Buffer.alloc(stride * height);
  let offset = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[offset++];
    if (filter > 4) throw new Error('Invalid PNG row filter');
    for (let x = 0; x < stride; x++) {
      const left = x >= channels ? output[y * stride + x - channels] : 0;
      const above = y ? output[(y - 1) * stride + x] : 0;
      const upperLeft = y && x >= channels ? output[(y - 1) * stride + x - channels] : 0;
      let value = raw[offset++];
      if (filter === 1) value += left;
      if (filter === 2) value += above;
      if (filter === 3) value += Math.floor((left + above) / 2);
      if (filter === 4) {
        const estimate = left + above - upperLeft;
        const a = Math.abs(estimate - left), b = Math.abs(estimate - above), c = Math.abs(estimate - upperLeft);
        value += a <= b && a <= c ? left : b <= c ? above : upperLeft;
      }
      output[y * stride + x] = value & 255;
    }
  }
  return {width, height, channels, output};
}

export function compareImages(first, second) {
  const a = pixels(first), b = pixels(second);
  if (a.width !== b.width || a.height !== b.height || a.channels !== b.channels) return {stable: false, visible_changed: true, dimensions_match: false, changed_pixels: Math.max(a.width*a.height, b.width*b.height), channel_tolerance: 8, minimum_input_pixels: 16};
  let changed = 0;
  for (let offset = 0; offset < a.output.length; offset += a.channels) {
    for (let channel = 0; channel < a.channels; channel++) {
      if (Math.abs(a.output[offset+channel] - b.output[offset+channel]) > 8) {changed++; break;}
    }
  }
  return {stable: changed === 0, visible_changed: changed >= 16, dimensions_match: true, changed_pixels: changed, channel_tolerance: 8, minimum_input_pixels: 16};
}
