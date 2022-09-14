#!/bin/sh

if [ ! -e /etc/postfix/main.cf -o -d /etc/postfix/main.cf ]; then
    echo "ERROR: /etc/postfix/main.cf must be a regular file, volume-mounted from the outside."
    exit 1
fi

if [ -n "$MYHOSTNAME" ]; then
    echo "$MYHOSTNAME" > /etc/mailname
    postconf myhostname="$MYHOSTNAME"
fi

if [ -n "$MYNETWORKS" ]; then
    postconf mynetworks="$MYNETWORKS"
fi

if [ -n "$RELAYHOST" ]; then
    postconf relayhost="$RELAYHOST"

    if [ -n "$RELAYUSER" ]; then
	rs="$RELAYHOST $RELAYUSER"
	if [ -n "$RELAYPASS" ]; then
	    rs="$rs:$RELAYPASS"
	fi
	echo "$rs" >> /etc/postfix/sasl/sasl_passwd
    fi
fi

/usr/lib/postfix/configure.sh - || (echo "ERROR: failed to configure postfix chroots, aborting"; exit 1)

/usr/sbin/postmap hash:/etc/postfix/sasl/sasl_passwd

cp -p /etc/resolv.conf /var/spool/postfix/etc/

exec /usr/sbin/postfix start-fg
