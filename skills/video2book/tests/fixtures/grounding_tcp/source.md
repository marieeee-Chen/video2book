# BLK01 P01 块级逐字稿

> 来源：**混合（B 站字幕 + 听音转录）**——逐集来源见下，非单一来源稿。
> B 站字幕集：无；听音转录集：P01。
> 字幕由平台生成，可能存在识别错误与断句偏差；听音稿由讲师原声转录、不含时间戳。

[听音转录 · P01 Screen Recording 2021-12-31 at 16.51.22]
> 来源：**听音转录**——非平台字幕，由讲师原声转录

嗯。好了，朋友们，今天我们要来继续讲讲transport layer里面最重要的一种。协议Transmission Control Protocol是俗称的TCP。TCP is a transport particle that is used on top of IP to ensure reliable transmission of packets.它保持一种可靠的传输。TCP includes mechanism to solve many of the problem that arise from packet is the messaging such as last packets all of water.A dupice packet and corrective packet.像我们之前说UCUDP一样，UDP呢它只管最后一种情况，也就是corrected。PacketsTCP在处理很多问题的情况下，他的一个想法就是通过如果我找到错了，那我们就重新来解决这个问题。他的方式就是通过收报确认和丢包重传来保证最后的结果。Since TCP is a particle use, most commonly on top of IP.The Internet Prodigal Stack is sometimes referred as TCP/IP.p呢是最常常用的一种方式，所以我们与其用u d p呢加ip的这种情况，还不如说是tcpip。这种组合是最常见的。Okay，下面就来说这个packet里面是怎么样一个封装的形式。我先进packets using TCP/IP，the data portion of each IP packets is formatted asp它也是包含在这个ip data的一个部分，tcphelder也是包含在ip data一部分，这段的data呢还是在下面的。所以我们具体来看一下，先看一下它的里面有些什么东西呢？Source port number and destination port number，就和UDP是一样的。Sequence number有点新鲜，好像跟之前说的有点不一样，居然还有什么acknowledgement number，听起来就是用了一套不一样的系统。那下面可以看到很多的看knowledge和相关的一些词。当然还有check some，是我们之前在u d p里面已经比较熟悉的一个概念。OK来看一下具体的Its TCP segment contains a header and data. The TCP header contains many more fields than the UDP header.It can range from size in size from 20 to 60 bytes.
