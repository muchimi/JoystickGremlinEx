# GremlinEx remote control setup

## General Context

GEX lets you send outputs from its mappings to other GEX clients on the **local** network.  

Use one GremlinEx (GEX) instance as the **master** to send mapped output to one or more **clients**. Start with all machines on the same trusted LAN, running the same GEX build. Use the same **Broadcast Port** on each machine. The default is UDP `6012`.

## 1. Set up the master

1. On the PC with the physical controls and mapping profile, open **Tools > Options > Remote Control**.
2. Enable **Enable server broadcast (must be enabled to control remote clients)** and check **Current host is the master GEX server**. Enabling broadcast switches this instance to the sending role.
3. Set **Broadcast Port** to `6012` or the UDP port you will use on every GEX instance.
4. Run `ipconfig` on the master and record the **IPv4 Address** of the Ethernet or Wi-Fi adapter that shares the clients' LAN. For example, if the master's Ethernet adapter shows `192.168.1.20`, use that address on the clients.
5. Leave **All IPs** checked to use the Windows default interface for outbound multicast. If the master has several adapters and Windows is using the wrong one, clear **All IPs**, click **Select** next to **GEX Master Server IPv4**, and choose the master's LAN adapter address from **Available IPs**.

## 2. Set up each receiving client

1. Open **Tools > Options > Remote Control**. Enable **Enable control of this client by a remote server**. Clear **Current host is the master GEX server** if it is checked. GEX switches off **Enable server broadcast** when you enable the receiving role.
2. Give the client a recognizable **Custom Client Name**, such as `Flight Display`, or use its Windows host name.
3. Set **Broadcast Port** to the same value as the master. Leave **All IPs** checked on the client.
4. Under **GEX connection test**, click **Discover…** next to **GEX Master Server IPv4**. Choose the master computer and its LAN IPv4 address, then click **Select** to save it. If Windows Network Discovery does not list the master, use the **Select** button next to the address field, enter the address in **Server IPv4**, and click **OK**.
5. Create or load a profile on the client. A blank profile works. Activate the profile when you're ready to receive output and keep it running while you use remote control. For vJoy output, configure the receiving vJoy device with the same device ID and corresponding axes, buttons, and hats used by the master mapping.

## 3. Check connectivity and open the firewall if needed

- **From a client**, click **Test Connection** under **GEX connection test**. Look for both **GEX responded … over UDP** and **Server multicast reached this PC**. The first confirms the direct UDP exchange with the master's IPv4 address. The second confirms that the master's multicast traffic reaches the client.
- **From the master**, click **Check Broadcast** in the same section. GEX sends a multicast ping and lists the clients that reply with their names and addresses. Repeat after bringing additional clients online. If the Tools menu is disabled on the PC where you are testing, stop its profile to open Options. The network tests can run before you activate a profile.
- If the direct test fails, verify the master's IPv4 address, its broadcast setting, the matching UDP port, and the master's inbound firewall rule. If the direct test succeeds but multicast fails, check the master's outbound and the client's inbound firewall policy, the selected adapter, and whether the LAN permits multicast. Guest Wi-Fi, client isolation, and VPN routing can interfere.

### Use GEX Firewall Check

1. On the affected PC, open **Tools > Options > Remote Control > Firewall Check...**. Verify that **UDP port** matches **Broadcast Port**.
2. On a client, select **Allow from a specific host** and confirm that **Server IPv4** contains the master's LAN address. The client rule covers inbound multicast to `224.3.29.72` from that address.
3. On the master, select **Allow from any host** if using the built-in rule. The master needs to receive unicast test requests and broadcast-check replies from the clients. To scope that rule to the client addresses, use the Windows procedure below.
4. If a rule is missing, click **Check / Add Rule** and approve the Windows elevation prompt if shown. **Apply** alone saves the port and host settings. If Windows reports a block rule or managed policy, review the rule or ask the administrator who manages it. Run both GEX tests again after the change.

### Add an inbound rule in Windows manually

1. Run `wf.msc` to open **Windows Defender Firewall with Advanced Security**. Choose **Inbound Rules > New Rule > Custom**.
2. On **Program**, choose the GEX executable if you want to limit the rule to that program. On **Protocol and Ports**, choose **UDP**, set **Local port** to the configured broadcast port, and leave **Remote port** at **All Ports**.
3. On **Scope**, use the master's IPv4 address as the **remote** IP on a client. You can scope the client's **local** IP to the multicast group `224.3.29.72`. On the master, leave the **local** addresses unrestricted to cover unicast and multicast and set the **remote** addresses to the participating client IPv4 addresses.
4. Choose **Allow the connection**, select the profile used by the trusted LAN, and give the rule a descriptive name. Repeat on the machine that needs an inbound rule, then rerun the GEX tests. [Microsoft's inbound port rule instructions](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/configure#create-an-inbound-port-rule)

## 4. Register clients on the master

1. Open **Tools > Remote Clients…** on the master. You can also use **Manage Remote Clients…** in the **Remote Control** options or **Edit Clients…** in a client checklist.
2. Click **Refresh GEX Clients** to ask running GEX instances to register. To save one directly, enter its IPv4 address or network name and click **Add**. **Auto Discover** adds computers found by Windows Network Discovery, so use **Check Broadcast** to verify which ones are responding as GEX clients.
3. Use the saved entries to target particular machines in a profile. **Enable all** and **Select All** can include eligible clients beyond the saved list.

## 5. Choose what happens at profile start

On the master, open the profile's **Profile Settings** tab and find **Remote Control at Profile Start**. Set **Mode** to choose the client filter and **Routing** to choose the output destination. Save the profile, then activate it to apply these settings. If it was already active, stop and restart it.

| To start the profile with | Mode | Routing |
| --- | --- | --- |
| Output on the master only | **No change** | **Local** |
| Output on every eligible client | **Enable all** | **Remote** |
| Output on the master and specific clients | **Selection** and check the clients | **Both** |
| Local output and every remote client muted | **Mute all** | **Local** |

**No change** keeps the current setting for that field. In **Selection**, use **Solo** to select one client or **Select All** to include all eligible clients, including newly discovered ones. Use **Mute all** for an explicit startup mute. An empty startup **Selection** enables all clients.

## 6. Manage clients while the profile is running

1. In the master profile, choose a joystick button, hat direction, or keyboard input and add the **Remote Control** action.
2. Under **Mode**, choose **Selection** and check the desired clients, choose **Enable all**, or choose **Mute all**. Use **No change** to adjust routing while keeping the current client filter. In this action, **Selection** with an empty checklist is skipped at runtime.
3. Under **Routing**, choose **Local**, **Remote**, **Both**, or **No change**. For example, choose **Mute all** with **Both** to mute the clients and keep local output enabled. Use a second action with **Enable all** and **No change** to restore the clients without changing routing.
4. Choose when the action applies. With both behavior boxes clear, the filter stays in effect until another command changes it. **Hold** applies the client filter on press and restores the previous filter on release. **Toggle on each trigger** applies or removes a **Selection** on successive triggers. For toggling once per press, check **Execute on press** and clear **Execute on release**. A change requested under **Routing** stays in effect after releasing a held filter or toggling it off. Choose **No change** for a client-only override.

## 7. Verify mapped output

1. Run the profile on the master and a profile on each receiving client.
2. Use a remote-capable action such as **Map to Keyboard/Mouse Ex** or **Vjoy Remap**. For an initial test, leave **Custom output configuration** off in **Map to Keyboard/Mouse Ex** so it uses the profile routing and default **Any** client target. For an existing mapping with custom output, check its local and remote settings and ensure its target list includes the client.
3. For example, map a spare button to type a letter with **Map to Keyboard/Mouse Ex**. Open a text editor on the client, set the master profile to **Remote** with that client selected, then press the mapped button. Confirm the letter appears on the client. Trigger **Mute all**, then press the mapped button again to confirm that remote output stops.
