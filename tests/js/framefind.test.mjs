// node --test tests/js — перехід до аркуша за набраним номером чи назвою.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { frameIndex } from '../../src/nyshporka/daemon/static/core/framefind.js';

const frames = ['00001.jpg', '00002.jpg', '03090.jpg', 'film_00412.jpg', 'obkladynka.png']
  .map((label) => ({ label }));

test('назва кадру, з розширенням і без', () => {
  assert.equal(frameIndex(frames, '03090.jpg'), 2);
  assert.equal(frameIndex(frames, '03090'), 2);
  assert.equal(frameIndex(frames, ' 03090 '), 2);
});

test('число без нулів і число в хвості назви', () => {
  assert.equal(frameIndex(frames, '3090'), 2);
  assert.equal(frameIndex(frames, '412'), 3);
});

test('назва сильніша за номер за порядком', () => {
  // «2» — це кадр 00002, а не другий за порядком (тут вони збігаються), а «4» — четвертий.
  assert.equal(frameIndex(frames, '2'), 1);
  assert.equal(frameIndex(frames, '4'), 3);
});

test('шматок назви і промах', () => {
  assert.equal(frameIndex(frames, 'obkl'), 4);
  assert.equal(frameIndex(frames, '99999'), -1);
  assert.equal(frameIndex(frames, ''), -1);
  assert.equal(frameIndex([], '1'), -1);
});
