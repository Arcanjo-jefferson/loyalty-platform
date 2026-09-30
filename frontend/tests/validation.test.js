import test from 'node:test'
import assert from 'node:assert/strict'
import { birthDateError, irelandToday, latestAdultBirthDate, normalizeIrishMobile } from '../src/validation.js'

test('Irish mobiles normalize consistently and malformed inputs fail', () => {
  for (const input of ['0871234567', '+353871234567', '087 123 4567', '+353 (87) 123-4567']) assert.equal(normalizeIrishMobile(input), '+353871234567')
  for (const input of ['087', '087123456', '08712345678', '087abcdefg', '0871234567!', '+3530871234567', '0881234567', '+44871234567']) assert.equal(normalizeIrishMobile(input), null)
})

test('age uses full date and rejects invalid and future dates', () => {
  const today = '2026-09-29'
  assert.equal(birthDateError('2008-09-29', today), '')
  assert.equal(birthDateError('2008-09-30', today), 'Customer must be at least 18 years old.')
  assert.equal(birthDateError('2026-09-30', today), 'Date of birth cannot be in the future.')
  assert.equal(birthDateError('2000-02-30', today), 'Enter a valid date of birth.')
  assert.equal(birthDateError('', today), 'Enter a valid date of birth.')
  assert.equal(birthDateError('2008-02-29', '2026-02-28'), 'Customer must be at least 18 years old.')
  assert.equal(birthDateError('2008-02-29', '2026-03-01'), '')
  assert.equal(latestAdultBirthDate('2026-09-29'), '2008-09-29')
  assert.equal(latestAdultBirthDate('2024-02-29'), '2006-02-28')
})

test('business date uses Dublin timezone', () => {
  assert.equal(irelandToday(new Date('2026-09-28T23:30:00Z')), '2026-09-29')
})
