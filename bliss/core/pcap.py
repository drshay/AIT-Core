# Copyright 2016 California Institute of Technology.  ALL RIGHTS RESERVED.
# U.S. Government Sponsorship acknowledged.

"""
This module, pcap.py, is a library to read/write PCAP-formatted files with
simple open, read, write, close functions
"""

import __builtin__
import struct
import dmc
import datetime


"""
Check the endian of the host we are currently running on.
"""
if struct.pack('@I', 0xA1B2C3D4) == struct.pack('>I', 0xA1B2C3D4):
    EndianSwap = '<'
else:
    EndianSwap = '>'


class PCapGlobalHeader:
    """PCapGlobalHeader

    Represents a PCap global header.  See:

        https://wiki.wireshark.org/Development/LibpcapFileFormat
    """

    def __init__ (self, stream=None):
        """Creates a new PCapGlobalHeader with default values.  If a stream
        is given, the global header data is read from it.
        """
        self._format = 'IHHiIII'
        self._size   = struct.calcsize(self._format)
        self._swap   = '@'

        if stream is None:
            self.magic_number  = 0xA1B2C3D4
            self.version_major = 2
            self.version_minor = 4
            self.thiszone      = 0
            self.sigfigs       = 0
            self.snaplen       = 65535
            self.network       = 147
            self._data         = str(self)
        else:
            self.read(stream)


    def __len__ (self):
        """Returns the number of bytes in this PCapGlobalHeader."""
        return len(self._data)


    def __str__ (self):
        """Returns this PCapGlobalHeader as a binary string."""
        return struct.pack( self._format,
                            self.magic_number ,
                            self.version_major,
                            self.version_minor,
                            self.thiszone     ,
                            self.sigfigs      ,
                            self.snaplen      ,
                            self.network )


    def incomplete (self):
        """Indicates whether or not this PCapGlobalHeader is incomplete."""
        return len(self) < self._size


    def read (self, stream):
        """Reads PCapGlobalHeader data from the given stream."""
        self._data = stream.read(self._size)

        if len(self._data) >= self._size:
            values = struct.unpack(self._format, self._data)
        else:
            values = None, None, None, None, None, None, None

        if   values[0] == 0xA1B2C3D4 or values[0] == 0xA1B23C4D:
            self._swap = '@'
        elif values[0] == 0xD4C3B2A1 or values[0] == 0x4D3CB2A1:
            self._swap = EndianSwap

        if values[0] is not None:
            values = struct.unpack(self._swap + self._format, self._data)

        self.magic_number  = values[0]
        self.version_major = values[1]
        self.version_minor = values[2]
        self.thiszone      = values[3]
        self.sigfigs       = values[4]
        self.snaplen       = values[5]
        self.network       = values[6]



class PCapPacketHeader:
    """PCapPacketHeader

    Represents a PCap packet header.  See:

        https://wiki.wireshark.org/Development/LibpcapFileFormat
    """

    def __init__ (self, stream=None, swap=None, orig_len=0, maxlen=65535):
        """Creates a new PCapPacketHeader with default values.  If a stream is
        given, the packet header data is read from it.
        """
        if swap is None:
           swap = '@'

        self._format = 'IIII'
        self._size   = struct.calcsize(self._format)
        self._swap   = swap

        if stream is None:
            self.ts_sec, self.ts_usec = dmc.getTimestampUTC()
            self.incl_len             = min(orig_len, maxlen)
            self.orig_len             = orig_len
            self._data                = str(self)
        else:
            self.read(stream)


    def __len__ (self):
        """Returns the number of bytes in this PCapPacketHeader."""
        return len(self._data)


    def __str__ (self):
        """Returns this PCapPacketHeader as a binary string."""
        return struct.pack( self._format ,
                            self.ts_sec  ,
                            self.ts_usec ,
                            self.incl_len,
                            self.orig_len )


    @property
    def timestamp (self):
        """Packet timestamp as a Python Datetime object"""
        return datetime.datetime.utcfromtimestamp( self.ts )


    @property
    def ts (self):
        """Packet timestamp as a float, a combination of ts_sec and ts_usec"""
        return float(self.ts_sec) + (float(self.ts_usec) / 1e6)


    def incomplete (self):
        """Indicates whether or not this PCapGlobalHeader is incomplete."""
        return len(self) < self._size


    def read (self, stream):
      """Reads PCapPacketHeader data from the given stream."""
      self._data = stream.read(self._size)

      if len(self._data) >= self._size:
          values = struct.unpack(self._swap + self._format, self._data)
      else:
          values = None, None, None, None

      self.ts_sec   = values[0]
      self.ts_usec  = values[1]
      self.incl_len = values[2]
      self.orig_len = values[3]



class PCapStream:
    """PCapStream

    PCapStream is the primary class of the pcap.py module.  It exposes
    open(), read(), write(), and close() methods to read and write
    pcap-formatted files.

    See:

        https://wiki.wireshark.org/Development/LibpcapFileFormat
    """

    def __init__(self, stream, mode='rb'):
        """Creates a new PCapStream, which wraps the underlying Python stream,
        already opened in the given mode.
        """
        if mode.startswith('r'):
            self.header = PCapGlobalHeader(stream)
        elif mode.startswith('w') or (mode.startswith('a') and stream.tell() == 0):
            self.header = PCapGlobalHeader()
            stream.write( str(self.header) )

        self._stream = stream


    def __enter__ (self):
        """A PCapStream provies a Python Context Manager interface."""
        return self


    def __exit__ (self, type, value, traceback):
        """A PCapStream provies a Python Context Manager interface."""
        self.close()


    def __next__ (self):
        """Provides Python 3 iterator compatibility.  See next()."""
        return self.next()


    def __iter__ (self):
        """A PCapStream provides a Python iterator interface."""
        return self


    def next (self):
        """Returns the next header and packet from this
        PCapStream. See read().
        """
        header, packet = self.read()

        if packet is None:
            raise StopIteration

        return header, packet


    def read (self):
        """Reads a single packet from the this pcap stream, returning a
        tuple (PCapPacketHeader, packet)
        """
        header = PCapPacketHeader(self._stream, self.header._swap)
        packet = None

        if not header.incomplete():
            packet = self._stream.read(header.incl_len)

        return (header, packet)


    def write (self, bytes):
        """write() is meant to work like the normal file write().  It takes
        one argument, a byte array to write to the file as a single
        PCAP packet.  The length of the byte array should be less than
        65535 bytes.  write() returns the number of bytes actually
        written to the file.
        """
        if type(bytes) is str:
            bytes = bytearray(bytes)

        header = PCapPacketHeader(orig_len=len(bytes))
        packet = bytes[0:header.incl_len]

        self._stream.write( str(header) )
        self._stream.write( packet      )
        self._stream.flush()

        return header.incl_len


    def close (self):
        """Closes this PCapStream by closing the underlying Python stream."""
        self._stream.close()



def open (filename, mode='r'):
    """Returns an instance of a PCapStream class which contains the
    read(), write(), and close() methods.  Binary mode is assumed for
    this module, so the "b" is not required when calling open().  A
    max packet length can also be passed in if the default (65535) is
    insufficient.
    """
    mode   = mode.replace('b', '') + 'b'
    stream = PCapStream( __builtin__.open(filename, mode), mode )

    return stream


def query(filename, starttime, endtime, outname=None):
    '''Given a time range and input file, query creates a new file with only
    that subset of data. If no outfile name is given, the new file name is the
    old file name with the time range appended.
    '''
    if outname is not None:
       outname = filename.replace('.pcap','').append(timerange).append('.pcap')

    start = datetime.datetime.utcfromtimestamp(starttime)
    end = datetime.datetime.utcfromtimestamp(endtime)

    with __builtin__.open(outname,'wb') as outfile:

        with pcap.open(filename, 'r') as stream:
            header, packet = stream.read()
            if packet is not None:
                if header.timestamp <= start and header.timestamp > end:
                   outfile.write(header.__str__())
                   outfile.write(packet)

