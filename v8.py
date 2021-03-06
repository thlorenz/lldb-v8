# Copyright Joyent, Inc. and other Node contributors. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

import lldb
import shlex
import struct
import traceback

from utils import *

SYMBOLS = {
	'major': ['_ZN2v88internal7Version6major_E'],
	'minor': ['_ZN2v88internal7Version6minor_E'],
	'build': ['_ZN2v88internal7Version6build_E'],
	'patch': ['_ZN2v88internal7Version6patch_E'],

	'V8_OFF_FP_CONTEXT': ['v8dbg_off_fp_context'],
	'V8_OFF_FP_FUNCTION': ['v8dbg_off_fp_function'],
	'V8_OFF_FP_MARKER': ['v8dbg_off_fp_marker'],
	'V8_OFF_FP_ARGS': ['v8dbg_off_fp_args'],

	'V8_FirstNonstringType': ['v8dbg_FirstNonstringType'],
	'V8_IsNotStringMask': ['v8dbg_IsNotStringMask'],
	'V8_StringTag': ['v8dbg_StringTag'],
	'V8_NotStringTag': ['v8dbg_NotStringTag'],
	'V8_StringEncodingMask': ['v8dbg_StringEncodingMask'],
	'V8_TwoByteStringTag': ['v8dbg_TwoByteStringTag'],
	'V8_AsciiStringTag': ['v8dbg_AsciiStringTag'],
	'V8_StringRepresentationMask': ['v8dbg_StringRepresentationMask'],
	'V8_SeqStringTag': ['v8dbg_SeqStringTag'],
	'V8_ConsStringTag': ['v8dbg_ConsStringTag'],
	'V8_SlicedStringTag': ['v8dbg_SlicedStringTag', None, 0x3],

	'V8_ExternalStringTag': ['v8dbg_ExternalStringTag'],
	'V8_FailureTag': ['v8dbg_FailureTag'],
	'V8_FailureTagMask': ['v8dbg_FailureTagMask'],
	'V8_HeapObjectTag': ['v8dbg_HeapObjectTag'],
	'V8_HeapObjectTagMask': ['v8dbg_HeapObjectTagMask'],
	'V8_SmiTag': ['v8dbg_SmiTag'],
	'V8_SmiTagMask': ['v8dbg_SmiTagMask'],
	'V8_SmiValueShift': ['v8dbg_SmiValueShift'],
	'V8_SmiShiftSize': ['v8dbg_SmiShiftSize', None, 0],

	'V8_PointerSizeLog2': ['v8dbg_PointerSizeLog2'],

	'V8_DICT_SHIFT': ['v8dbg_dict_shift', '3.13', 24 ],
	'V8_DICT_PREFIX_SIZE': ['v8dbg_dict_prefix_size', '3.11', 2 ],
	'V8_DICT_ENTRY_SIZE': ['v8dbg_dict_entry_size', '3.11', 3],
	'V8_DICT_START_INDEX': ['v8dbg_dict_start_index', '3.11', 3],
	'V8_ISSHARED_SHIFT': ['v8dbg_isshared_shift', '3.11', 0],
	'V8_PROP_IDX_FIRST': ['v8dbg_prop_idx_first'],
	'V8_PROP_TYPE_FIELD': ['v8dbg_prop_type_field'],
	'V8_PROP_FIRST_PHANTOM': ['v8dbg_prop_type_first_phantom'],
	'V8_PROP_TYPE_MASK': ['v8dbg_prop_type_mask'],
	'V8_PROP_IDX_CONTENT': ['v8dbg_prop_idx_content', None],
	'V8_PROP_DESC_KEY': ['v8dbg_prop_desc_key', None, 0],
	'V8_PROP_DESC_DETAILS': ['v8dbg_prop_desc_details', None, 1],
	'V8_PROP_DESC_VALUE': ['v8dbg_prop_desc_value', None, 2],
	'V8_PROP_DESC_SIZE': ['v8dbg_prop_desc_size', None, 3],
	'V8_TRANSITIONS_IDX_DESC': ['v8dbg_transitions_idx_descriptors', None ],

	'V8_ELEMENTS_KIND_SHIFT': ['v8dbg_elements_kind_shift', None, 3],
	'V8_ELEMENTS_KIND_BITCOUNT': ['v8dbg_elements_kind_bitcount', None, 5],
	'V8_ELEMENTS_FAST_ELEMENTS': ['v8dbg_elements_fast_elements', None, 2],
	'V8_ELEMENTS_FAST_HOLEY_ELEMENTS': ['v8dbg_elements_fast_holey_elements', None, 3],
	'V8_ELEMENTS_DICTIONARY_ELEMENTS': ['v8dbg_elements_dictionary_elements', None, 6],
}

class V8Cfg:
  def __init__(self, target):
    self.target = target
    self.process = target.GetProcess()

    self.frametype = {}
    self.classes = {}
    self.types = {}

    delay = []
    for key, value in SYMBOLS.iteritems():
      ret = self.load_symbol(value[0])
      if isinstance(ret, lldb.SBError):
        raise ret
      elif ret is None:
        if len(value) == 3:
          ret = value[2]
        elif len(value) == 2:
          pass
        else:
          print 'failed to load symbol: ', key

      if ret is not None:
        setattr(self, key, ret)

    for i in range(target.GetNumModules()):
      mod = target.GetModuleAtIndex(i)
      for j in range(mod.GetNumSymbols()):
        sym = mod.GetSymbolAtIndex(j)
        if 'v8dbg_frametype_' in sym.name:
          val = self.load_symbol(sym.name)
          key = sym.name.replace('v8dbg_frametype_', '')
          self.frametype[key] = val
          self.frametype[val] = key
        elif 'v8dbg_parent_' in sym.name:
          val = self.load_symbol(sym.name)
          key = sym.name.replace('v8dbg_parent_', '').split('__')
          parent = key[1]
          child = key[0]
          parent_klass = self.classes.get(parent)
          child_klass = self.classes.get(child)

          if not parent_klass:
            parent_klass = {}

          parent_klass['!name'] = parent

          if not child_klass:
            child_klass = {}

          child_klass['!name'] = child
          child_klass['!parent'] = parent_klass

          self.classes[parent] = parent_klass
          self.classes[child] = child_klass
        elif 'v8dbg_class_' in sym.name:
          val = self.load_symbol(sym.name)
          key = sym.name.replace('v8dbg_class_', '').split('__')


          kname = key[0]
          field = key[1]
          ktype = key[2]

          klass = self.classes.get(kname)

          if not klass:
            klass = {}

          klass['!name'] = kname

          klass[field] = {
            'type': ktype,
            'name': field,
            'offset': val,
          }

          self.classes[kname] = klass
        elif 'v8dbg_type_' in sym.name:
          val = self.load_symbol(sym.name)
          key = sym.name.replace('v8dbg_type_', '')
          self.types[key] = val
          self.types[val] = key

    major = self.major
    minor = self.minor
    build = self.build
    patch = self.patch

    self.version = '{major}.{minor}.{build}.{patch}'.format(**locals())

  def load_symbol(self, symbol):
    syms = self.target.FindSymbols(symbol)
    error = lldb.SBError()
    if len(syms.symbols):
      symbol = syms.symbols[0]
      size = int(symbol.end_addr) - int(symbol.addr)
      val = self.process.ReadMemory(int(symbol.addr), size, error)
      if error.Success():
        return bytearray_to_int(val, size)
      else:
        return error
    else:
      return None

  def v8_is_smi(self, addr):
    smi = self.V8_SmiTag
    mask = self.V8_SmiTagMask
    return ((addr & mask) == smi)

  def v8_smi(self, addr):
    val = self.V8_SmiValueShift
    sze = self.V8_SmiShiftSize
    return (addr >> (val + sze))

  def get_offset(self, name):
    parts = name.split('.')
    klass = self.classes.get(parts[0])
    member = klass.get(parts[1])
    return member['offset'] - 1

  def read_type(self, addr):
    heapoff = self.get_offset('HeapObject.map')
    mask = self.V8_HeapObjectTagMask
    tag = self.V8_HeapObjectTag
    aoff = self.get_offset('Map.instance_attributes')

    error = lldb.SBError()

    maddr = self.process.ReadPointerFromMemory(addr + heapoff, error)

    if not error.Success():
      #print (hex(addr), heapoff, hex(addr + heapoff), 'failed to get maddr')
      #print ''.join(traceback.format_stack())
      return error

    if (maddr & mask) != tag:
      #print 'not a heapobject'
      return False

    hbyte = self.process.ReadMemory(maddr + aoff, 1, error)

    if not error.Success():
      #print (hex(maddr), aoff, hex(maddr + aoff), 'failed to get hbyte')
      return error

    hbyte = bytearray_to_uint(hbyte, 1)

    return self.types[hbyte]

  def read_heap_smi(self, addr, off):
    error = lldb.SBError()
    ptr = self.process.ReadPointerFromMemory(addr + off, error)

    if not error.Success():
      return error

    return self.v8_smi(ptr)

  def jstr_print_seq(self, addr):
    strlen = self.get_offset('String.length')
    slen = self.read_heap_smi(addr, strlen)
    if isinstance(slen, lldb.SBError):
      return slen

    if not slen:
      return ''

    off = self.get_offset('SeqAsciiString.chars')

    error = lldb.SBError()

    blob = self.process.ReadMemory(addr + off, slen, error)

    if not error.Success():
      return error

    return blob

  def jstr_print_cons(self, addr):
    first = self.get_offset('ConsString.first')
    second = self.get_offset('ConsString.second')

    error = lldb.SBError()

    ptr1 = self.process.ReadPointerFromMemory(addr + first, error)

    if not error.Success():
      return error

    ptr2 = self.process.ReadPointerFromMemory(addr + second, error)

    if not error.Success():
      return error

    part1 = self.jstr_print(ptr1)

    if isinstance(part1, lldb.SBError):
      return part1

    part2 = self.jstr_print(ptr2)

    if isinstance(part2, lldb.SBError):
      return part2

    return part1 + part2
	
  def jstr_print(self, addr):
    typename = self.read_type(addr)

    if 'SeqAsciiString' in typename:
      typename = self.jstr_print_seq(addr)
    elif 'ConsString' in typename:
      typename = self.jstr_print_cons(addr)

    return typename

  def jsfunc_name(self, pointer):
    error = lldb.SBError()
    off = self.get_offset('SharedFunctionInfo.name')

    fstr = self.process.ReadPointerFromMemory(pointer + off, error)

    if not error.Success():
      return error

    name = self.jstr_print(fstr)

    if not name:
      name = 'anonymous'
      off = self.get_offset('SharedFunctionInfo.inferred_name')
      fstr = self.process.ReadPointerFromMemory(pointer + off, error)

      if not error.Success():
        return error

      inferred = self.jstr_print(fstr)

      if not inferred:
        inferred = 'anon'

      name = name + ' (as %s)' % inferred

    return name

  def obj_jstype(self, arg):
    failmask = self.V8_FailureTagMask
    failtag = self.V8_FailureTag

    if (arg & failmask) == failtag:
      return "'Failure' Object"

    if self.v8_is_smi(arg):
      return 'SMI: value = %d' % (self.v8_smi(arg))

    typename = self.read_type(arg)

    if isinstance(typename, lldb.SBError):
      return typename

    typename = typename.split('__')[0]

    if 'Oddball' in typename:
      error = lldb.SBError()
      off = self.get_offset('Oddball.to_string')
      ptr = self.process.ReadPointerFromMemory(arg + off, error)

      if not error.Success():
        return error

      sstr = self.jstr_print(ptr)

      if isinstance(sstr, lldb.SBError):
        return sstr

      typename += ': "%s"' % (sstr)

    return typename

  def jsargs(self, func, fp):
    off = self.get_offset('SharedFunctionInfo.length')
    nargs = self.read_heap_smi(func, off)

    if isinstance(nargs, lldb.SBError):
      return nargs

    error = lldb.SBError()

    args = []
    for i in range(nargs):
      off = fp + self.V8_OFF_FP_ARGS
      off += (nargs - i - 1) * self.target.addr_size

      arg = self.process.ReadPointerFromMemory(off, error)

      if not error.Success():
        return error

      otype = self.obj_jstype(arg)

      if isinstance(otype, lldb.SBError):
        return otype

      args.append([arg, otype])

    return args

  def jsstack_frame(self, result, thread, fp):
    error = lldb.SBError()
    off = fp + self.V8_OFF_FP_CONTEXT
    pointer = self.process.ReadPointerFromMemory(off, error)

    if not error.Success():
      print >> result, 'error: ', error
      return

    if self.v8_is_smi(pointer):
      smi = self.v8_smi(pointer)
      ft = self.frametype.get(smi, None)
      if ft:
        return {
          'fp': fp,
          'val': '<{ft}>'.format(ft=ft),
        }

    off = fp + self.V8_OFF_FP_MARKER
    pointer = self.process.ReadPointerFromMemory(off, error)

    if not error.Success():
      print >> result, error
      return

    if self.v8_is_smi(pointer):
      smi = self.v8_smi(pointer)
      ft = self.frametype.get(smi, None)
      if ft:
        return {
          'fp': fp,
          'val': '<{ft}>'.format(ft=ft),
        }

    off = fp + self.V8_OFF_FP_FUNCTION
    pointer = self.process.ReadPointerFromMemory(off, error)

    if not error.Success():
      print >> result, 'error: ', error
      return
	
    typename = self.read_type(pointer)

    if isinstance(typename, lldb.SBError):
      print >> result, typename
      return

    if not typename:
      #print >> result, '{addr:#016x} not a heap object'.format(addr=pointer)
      return

    if 'Code' in typename:
      return {
        'fp': fp,
        'val': 'internal (Code: {pointer:#016x})'.format(pointer= pointer),
      }

    off = self.get_offset('JSFunction.shared')

    func = self.process.ReadPointerFromMemory(pointer + off, error)

    if not error.Success():
      return error

    funcname = self.jsfunc_name(func)

    if isinstance(funcname, lldb.SBError):
      return funcname

    args = self.jsargs(func, fp)

    if isinstance(args, lldb.SBError):
      return args

    fargs = []

    for arg in args:
      fargs.append('{arg:#x} [{otype}]'.format(arg=arg[0], otype=arg[1]))

    if len(fargs):
      val = '<%s> (%s)' % (funcname, ', '.join(fargs))
    else:
      val = '<%s>' % (funcname)

    return {
      'fp': fp,
      'val': val,
    }
	
  def jsstack_thread(self, thread, result):
    depth = thread.GetNumFrames()

    mods = get_module_names(thread)
    funcs = get_function_names(thread)
    symbols = get_symbol_names(thread)
    files = get_filenames(thread)
    lines = get_line_numbers(thread)
    addrs = get_pc_addresses(thread)

    for i in range(depth):
      frame = thread.GetFrameAtIndex(i)
      function = frame.GetFunction()

      load_addr = addrs[i].GetLoadAddress(self.target)
      if not function:
        file_addr = addrs[i].GetFileAddress()
        start_addr = frame.GetSymbol().GetStartAddress().GetFileAddress()
        symbol_offset = file_addr - start_addr
        mod=mods[i]
        if not mod:
          f = self.jsstack_frame(result, thread, frame.fp)
        else:
          f = {
            'fp': load_addr,
            'val': '{mod}`{symbol} + {offset}'.format(mod=mod, symbol=symbols[i], offset=symbol_offset),
          }

        if isinstance(f, lldb.SBError):
          print >> result, f
        elif f:
          print >> result, '  frame #{num}: {fp:#016x} {val}'.format(num=i, fp=f['fp'], val=f['val'])
        else:
          print >> result, '  frame #{num}: {fp:#016x} skipped'.format(num=i, fp=load_addr)
          #print >> result, '  frame #{num}: {addr:#016x} {mod}`{symbol} + {offset}'.format(num=i, addr=load_addr, mod=mod, symbol=symbols[i], offset=symbol_offset)
      else:
        print >> result, '  frame #{num}: {addr:#016x} {mod}`{func} at {file}:{line} {args}'.format(
          num=i, addr=load_addr, mod=mods[i],
        func='%s [inlined]' % funcs[i] if frame.IsInlined() else funcs[i],
        file=files[i], line=lines[i],
        args=get_args_as_string(frame, showFuncName=False) if not frame.IsInlined() else '()')

  def jsstack(self, result):
    threads = self.process.GetNumThreads()

    #for i in range(0):
    i = 0
    print >> result, 'thread #{i}'.format(i=i)
    self.jsstack_thread(self.process.GetThreadAtIndex(i), result)

  def jsobj_print(self, addr, depth=1):
    ret = {
      'address': addr,
    }

    if self.v8_is_smi(addr):
      ret['value'] = self.v8_smi(addr)
      ret['type'] = 'SMI'
    else:
      typename = self.read_type(addr)
      ret['type'] = typename.split('__')[0]

      if isinstance(typename, lldb.SBError):
        return typename

      if 'String' in typename:
        val = self.jstr_print(addr)

        if isinstance(val, lldb.SBError):
          return val

        ret['value'] = val
      elif 'JSObject' in typename:
        val = self.jsobj_print_jsobject(addr, depth=depth)

        if isinstance(val, lldb.SBError):
          return val

        ret['value'] = val

    return ret

  def read_heap_array(self, addr):
    atype = self.read_type(addr)

    if 'FixedArray' not in atype:
      return False

    length = self.read_heap_smi(addr, self.get_offset('FixedArrayBase.length'))

    if not length:
      return []

    off = self.get_offset('FixedArray.data')

    error = lldb.SBError()

    addr = self.process.ReadMemory(addr + off, length * self.target.addr_size, error)

    if not error.Success():
      return error

    arr = []

    for i in range(0, len(addr), self.target.addr_size):
      arr.append(bytearray_to_uint(addr[i : self.target.addr_size + i], self.target.addr_size))

    return arr

  def read_heap_dict(self, addr):
    properties = {}

    arr = self.read_heap_array(addr)

    if not arr or isinstance(arr, lldb.SBError):
      return arr
    elif not len(arr):
      return {}

    start = self.V8_DICT_START_INDEX
    size = self.V8_DICT_PREFIX_SIZE
    esize = self.V8_DICT_ENTRY_SIZE

    for i in range(start + size, len(arr), esize):
      if self.jsobj_is_undefined(addr):
        continue

      key = ''

      if self.v8_is_smi(arr[i]):
        key = str(self.v8_smi(arr[i]))
      else:
        if self.jsobj_is_hole(arr[i]):
          continue

        typename = self.read_type(arr[i])

        if not 'String' in typename:
          return typename

        key = self.jstr_print(arr[i])

      if key:
        properties[key] = arr[i + 1]

    return properties


  def jsobj_is_undefined(self, addr):
    return 'undefined' in jsobj_is_oddball(addr)

  def jsobj_is_hole(self, addr):
    return 'hole' in jsobj_is_oddball(addr)

  def jsobj_is_oddball(self, addr):
    typename = self.read_type(addr)

    if 'Oddball' in typename:
      error = lldb.SBError()
      off = self.get_offset('Oddball.to_string')
      ptr = self.process.ReadPointerFromMemory(addr + off, error)

      if not error.Success():
        return error

      return self.jstr_print(ptr)

    return ''

  def jsobj_print_jsobject(self, addr, depth=1, parent=None, member=None):
    if not depth:
      return { 'address': addr, 'value': None }

    error = lldb.SBError()

    off = self.get_offset('JSObject.properties')

    ptr = self.process.ReadPointerFromMemory(addr + off, error)

    if not error.Success():
      return error

    jstype = self.read_type(ptr)

    result = {}

    if 'FixedArray' not in jstype:
      result[jstype] = {
        'value': 'unknown',
        'type': jstype,
        'address': ptr,
      }
      return result

    off = self.get_offset('HeapObject.map')
    maddr = self.process.ReadPointerFromMemory(addr + off, error)

    if not error.Success():
      return error

    off = self.get_offset('JSObject.elements')
    elements = self.process.ReadPointerFromMemory(addr + off, error)

    if not error.Success():
      return error

    harray = self.read_heap_array(elements)

    if isinstance(harray, lldb.SBError):
      return harray

    if harray and len(harray):
      off = self.get_offset('Map.bit_field2')
      bitfield = self.process.ReadMemory(maddr + off, 1, error)

      if not error.Success():
        return error

      bitfield = bytearray_to_uint(bitfield, 1)

      kind = bit_field2 >> self.V8_ELEMENTS_KIND_SHIFT
      kind &= (1 << self.V8_ELEMENTS_KIND_BITCOUNT) - 1

      if kind == self.V8_ELEMENTS_FAST_ELEMENTS or kind == self.V8_ELEMENTS_FAST_HOLEY_ELEMENTS:
         pass
      elif kind == self.V8_ELEMENTS_DICTIONARY_ELEMENTS:
         pass

    if 'V8_DICT_SHIFT' in dir(self):
      off = self.get_offset('Map.bit_field3')
      bitfield = self.process.ReadPointerFromMemory(maddr + off, error)
      if not error.Success():
        return error

      if self.v8_smi(bitfield) & (1 << self.V8_DICT_SHIFT):
        print 'we have dict'
        properties = self.read_heap_dict(ptr)
        print properties
        return properties
    else:
      print 'no shift'

    props = self.read_heap_array(ptr)

    off = self.get_offset('Map.instance_descriptors')

    ptr = self.process.ReadPointerFromMemory(maddr + off, error)

    if not error.Success():
      return error

    descs = self.read_heap_array(ptr)

    off = self.get_offset('Map.inobject_properties')

    ninprops = self.process.ReadMemory(maddr + off, 1, error)

    if not error.Success():
      return error

    ninprops = bytearray_to_uint(ninprops, 1)

    if 'V8_PROP_IDX_CONTENT' not in dir(self):
      content = descs
    else:
      print 'we have prop idx'

    if len(descs) > self.V8_PROP_IDX_FIRST:
      rndescs = (len(descs) - self.V8_PROP_IDX_FIRST) / self.V8_PROP_DESC_SIZE
    else:
      rndescs = 0

    properties = {}

    for i in range(rndescs):
      baseidx = self.V8_PROP_IDX_FIRST + (i * self.V8_PROP_DESC_SIZE)
      keyidx = baseidx + self.V8_PROP_DESC_KEY
      validx = baseidx + self.V8_PROP_DESC_VALUE
      detidx = baseidx + self.V8_PROP_DESC_DETAILS

      key = self.jstr_print(descs[keyidx])

      val = content[validx]
      val = self.v8_smi(val) - ninprops

      if val < 0:
        print 'stored in object'
      else:
        if val > len(props) and val < rndescs:
          continue
        elif val > len(props):
          #print ('badkey', key, val)
          continue
        ptr = props[val]

      properties[key] = self.jsobj_print(ptr, depth=depth-1)

    return properties

def jsstack(debugger, command, result, internal_dict):
  v8cfg = internal_dict.get('v8cfg')

  if not v8cfg:
    v8cfg = V8Cfg(debugger.GetSelectedTarget())
    internal_dict['v8cfg'] = v8cfg

  v8cfg.jsstack(result)


def jsframe(debugger, command, result, internal_dict):
  args = shlex.split(command)
  fp = int(args[0], 16)

  v8cfg = internal_dict.get('v8cfg')

  if not v8cfg:
    v8cfg = V8Cfg(debugger.GetSelectedTarget())
    internal_dict['v8cfg'] = v8cfg

  thread = v8cfg.target.process.GetSelectedThread()
  frame = v8cfg.jsstack_frame(result, thread, fp)
  print >> result, frame

def jstype(debugger, command, result, internal_dict):
  args = shlex.split(command)
  addr = int(args[0], 16)

  v8cfg = internal_dict.get('v8cfg')

  if not v8cfg:
    v8cfg = V8Cfg(debugger.GetSelectedTarget())
    internal_dict['v8cfg'] = v8cfg

  frame = v8cfg.obj_jstype(addr)

  print >> result, frame

def jsprint(debugger, command, result, internal_dict):
  args = shlex.split(command)
  addr = int(args[0], 16)

  v8cfg = internal_dict.get('v8cfg')

  if not v8cfg:
    v8cfg = V8Cfg(debugger.GetSelectedTarget())
    internal_dict['v8cfg'] = v8cfg

  frame = v8cfg.jsobj_print(addr)

  import pprint

  print >> result, pprint.pprint(frame)

# And the initialization code to add your commands 
def __lldb_init_module(debugger, internal_dict):
  target = debugger.GetSelectedTarget()

  v8cfg = V8Cfg(target)
  internal_dict['v8cfg'] = v8cfg
  print 'Identified version: %s' % (v8cfg.version)
	
  debugger.HandleCommand('command script add -f v8.jsstack jsstack')
  debugger.HandleCommand('command script add -f v8.jsframe jsframe')
  debugger.HandleCommand('command script add -f v8.jsframe jstype')
  debugger.HandleCommand('command script add -f v8.jsprint jsprint')
