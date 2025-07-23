#!/usr/bin/env python3
import sys
import yaml
from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import Node
from mininet.log import setLogLevel, info
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.topo import Topo


from mininet.node import OVSSwitch

routers = {}
mininet_routers={}
hosts={}
mininet_hosts={}
subnets={}
def transform_binary_string(s):
    i = 0
    res=''
    while(len(s)<32):
        s+='0'
    while(len(s)-i-8>=0):
        res+=str(int(s[i:i+8],2))
        if(len(s)-i-8!=0):
            res+='.'
        i+=8
    return res



class LinuxRouter(Node):
    def config(self, **params):
        super(LinuxRouter, self).config(**params)
        # Enable forwarding on the router
        self.cmd('sysctl net.ipv4.ip_forward=1')

    def terminate( self ):
        self.cmd('sysctl net.ipv4.ip_forward=0')
        super(LinuxRouter, self).terminate()

def ip_to_bits(ip:str)-> str:
    octets = ip.split('.')
    bits = ''.join(f"{int(octet):08b}" for octet in octets)
    return bits

def get_subnet(ip :str, mask :str) -> str:
    subnet=""
    bits_ip=ip_to_bits(ip)
    bits_mask=ip_to_bits(mask)
    for i in range(32):
        if(bits_mask[i]=='1'):
            subnet += bits_ip[i]
        else:
            break
    return subnet

def get_mask_size(mask: str)-> int:
    bit_mask=ip_to_bits(mask)
    return bit_mask.count('1')

def same_subnet(ip1 :str, mask1:str, ip2:str, mask2:str) ->str:
    bits_mask1=ip_to_bits(mask1)
    bits_mask2=ip_to_bits(mask2)
    bits_ip1=ip_to_bits(ip1)
    bits_ip2=ip_to_bits(ip2)
    for i in range(32):
        if bits_mask1[i]==bits_mask2[i]=='1':
            if bits_ip1[i]!=bits_ip2[i]:
                return False
        else:
            break
    return True

def calculate_path(router:str,subnet:str, router_connection:dict) ->str:
    global routers, mininet_routers, hosts, mininet_hosts, subnets
    if subnet in router_connection[router]["subnets"]:
        return router    
    seen=[]
    temp_router_connection=router_connection.copy()
    to_expand=[]
    to_expand.append([router,'',0])

    while len(to_expand)>0:
        to_expand=sorted(to_expand, key=lambda x: x[2])
        candidate=to_expand[0]
        if subnet in temp_router_connection[candidate[0]]["subnets"]:
            return candidate[1]
        for connection in temp_router_connection[candidate[0]]["connections"]:
            if connection[0] not in seen:
                if(candidate[1]!=''):
                    to_expand.append([connection[0],candidate[1],connection[2]+candidate[2]])
                else:
                    to_expand.append([connection[0],connection[1],connection[2]+candidate[2]])
        seen.append(candidate[0])
        to_expand.pop(0)



    return router







def print_help():
    print("""usage: emulation.py [-h] [-d] definition
    A tool to define the emulation of a network.

    positional arguments:
    definition   the definition file of the network in YAML

    options:
    -h, --help   show this help message and exit
    -d, --draw   output a map of the routers in GraphViz format
    """)
def draw_network(yamlFileName):
    with open(yamlFileName) as f:
        data = yaml.safe_load(f)
    
    # Get routers
    routers = {}
    for router_name, interfaces in data.get("routers", {}).items():
        routers[router_name] = {}
        for iface, config in interfaces.items():
            routers[router_name][iface] = {
                "address": config["address"],
                "mask": config["mask"],
                "cost": config.get("cost", 1)
            }
    print("graph Network {")
    for router_name in routers.keys():
        print("\t"+router_name+" [shape=circle];")

    subnets={}
    for router,interfaces in routers.items():
        for config in interfaces.values():
            subnet= get_subnet(config["address"],config["mask"])
            if(subnet not in subnets):
                subnets[subnet]={}
                subnets[subnet]["routers"]=[router]
                subnets[subnet]["cost"]=config["cost"]
            else:
                subnets[subnet]["routers"].append(router)
    for subnet in subnets.values():
        for i in range(len(subnet["routers"])):
            for j in range(i+1,len(subnet["routers"])):
                cost=subnet["cost"]
                print(f'\t{subnet["routers"][i]} -- {subnet["routers"][j]} [label="{cost}"];')

    print("}")

class Topology(Topo):
    def build(self, **params):
        global routers, mininet_routers, hosts, mininet_hosts, subnets
        yamlFileName = params['yaml']

        with open(yamlFileName) as f:
                data = yaml.safe_load(f)
      
        # Get routers and add them to Mininet
        
        for router_name, interfaces in data.get("routers", {}).items():
            routers[router_name] = {}
            router = self.addHost(router_name, cls=LinuxRouter)
            mininet_routers[router_name]=router 
            for iface, config in interfaces.items():
                routers[router_name][iface] = {
                    "address": config["address"],
                    "mask": config["mask"],
                    "cost": config.get("cost", 1)
                }

        # Get hosts and add them to Mininet
        for host_name, interfaces in data.get("hosts",{}).items():
            hosts[host_name]={}
            host=self.addHost(host_name)
            mininet_hosts[host_name]=host
            for iface, config in interfaces.items():
                hosts[host_name][iface] = {
                    "address": config["address"],
                    "mask": config["mask"],
                    "subnet": get_subnet(config["address"],config["mask"])
                }


        #Create subnets dictionary
        for router,interfaces in routers.items():
            for interface,config in interfaces.items():
                subnet= get_subnet(config["address"],config["mask"])
                if(subnet not in subnets):
                    subnets[subnet]={}
                    subnets[subnet]["routers-interface"]=[[router,interface]]
                    subnets[subnet]["cost"]=config["cost"]
                    subnets[subnet]["host-interface"]=[]
                else:
                    subnets[subnet]["routers-interface"].append([router,interface])
        for host, interfaces in hosts.items():
            for interface, config in interfaces.items():
                subnet= get_subnet(config["address"],config["mask"])
                subnets[subnet]["host-interface"].append([host, interface])
        #Create switches for subnets with netmask<=29
        switches={}
        mininet_switches={}
        for subnet in subnets: 
            if len(subnet)<=29:
                name="s"+str(len(switches)+1)
                switch = self.addSwitch(name)
                mininet_switches[name]=switch
                subnets[subnet]["switch"]=name
                switches[name]={}
                switches[name]["subnet"]=subnet
                switches[name]["routers-interface"]=subnets[subnet]["routers-interface"]
                switches[name]["host-interface"]=subnets[subnet]["host-interface"]

        #Create links
        for subnet in subnets.values():
            #Connect subnets with switches
            if "switch" in subnet: 
                #Connect routers to switch
                switch_name=subnet["switch"]
                for i in range(len(subnet["routers-interface"])):
                    router_name=subnet["routers-interface"][i][0]
                    interface_name=subnet["routers-interface"][i][1]
                    router_ip=routers[router_name][interface_name]["address"]
                    router_netmask=ip_to_bits(routers[router_name][interface_name]["mask"]).count('1')
                    self.addLink(mininet_switches[switch_name],mininet_routers[router_name], intfName1= f'{switch_name}-eth{i}', intfName2= f'{router_name}-{interface_name}', param2={'ip':f'{router_ip}/{router_netmask}' })
                #Connect host to switch
                for i in range(len(subnet["host-interface"])):
                    host_name=subnet["host-interface"][i][0]
                    interface_name=subnet["host-interface"][i][1]
                    host_ip=hosts[host_name][interface_name]["address"]
                    host_netmask=ip_to_bits(hosts[host_name][interface_name]["mask"]).count('1')
                    self.addLink(mininet_hosts[host_name],mininet_switches[switch_name], intfName1= f'{host_name}-{interface_name}', param1={'ip':f'{host_ip}/{host_netmask}'} )
            #Connect subnets without switches
            else:
                if len(subnet["routers-interface"])==2:
                    first_router_name=subnet["routers-interface"][0][0]
                    first_interface_name=subnet["routers-interface"][0][1]
                    second_router_name=subnet["routers-interface"][1][0]
                    second_interface_name=subnet["routers-interface"][1][1]
                    self.addLink(mininet_routers[first_router_name], mininet_routers[second_router_name],
                                intfName1= f'{first_router_name}-{first_interface_name}', intfName2= f'{second_router_name}-{second_interface_name}')
                else: 
                    router_name=subnet["routers-interface"][0][0]
                    router_interface_name=subnet["routers-interface"][0][1]
                    host_name=subnet["host-interface"][0][0]
                    host_interface_name=subnet["host-interface"][0][1]
                    self.addLink(mininet_routers[router_name], mininet_hosts[host_name],
                                intfName1= f'{router_name}-{router_interface_name}', intfName2= f'{host_name}-{host_interface_name}')
    




def main():
    global routers, mininet_routers, hosts, mininet_hosts, subnets

#HELP FUNCTION
    if len(sys.argv)==2 and sys.argv[1] in ('-h', '--help'):
        print_help()
#DRAW FUNCTION
    elif len(sys.argv)==3 and sys.argv[1] in ('-d', '--draw'):
        yamlFileName = sys.argv[2]
        draw_network(yamlFileName)
#START THE MININET EMULATOR
    elif len(sys.argv)==2:
        yamlFileName = sys.argv[1]
        t = Topology(yaml=yamlFileName)
        net = Mininet(topo=t, link=TCLink)
        net.start()


        #Create host interfaces
        for host,interfaces in hosts.items():
            for interface,config in interfaces.items():
                net[host].cmd(f'ifconfig {host}-{interface} {config["address"]} netmask {config["mask"]}')
                net[host].cmd(f'ifconfig {host}-{interface} up')
        #Create router interfaces
        for router,interfaces in routers.items():
            for interface,config in interfaces.items():
                net[router].cmd(f'ifconfig {router}-{interface} {config["address"]} netmask {config["mask"]}')
                net[router].cmd(f'ifconfig {router}-{interface} up')
        #Set default routes for hosts
        for value in subnets.values():
            for item in value["host-interface"]:
                host_name= item[0]
                host_interface=item[1]
                router_address= routers[value["routers-interface"][0][0]][value["routers-interface"][0][1]]["address"]
                net[host_name].cmd(f'ip route add default via {router_address} dev {host_name}-{host_interface}')
        
        #Find cheapest path for routers
        router_connection={}
        for router,interfaces in routers.items():
                router_connection[router]={}
                router_connection[router]["subnets"]=[]
                router_connection[router]["connections"]=[]
                for interface,config in interfaces.items():
                    subnet= get_subnet(config["address"],config["mask"])
                    router_connection[router]["subnets"].append(subnet)
                    for values in subnets[subnet]["routers-interface"]:
                        if values[0]!=router:
                            router_connection[router]["connections"].append([values[0],routers[values[0]][values[1]]["address"], subnets[subnet]["cost"]])
        #Add cheapest path to router ip routes
        for router in routers:
            for subnet in subnets:        
                best_route=calculate_path(router,subnet, router_connection)
                if(best_route!=router):
                    mask_size=len(subnet)
                    decimal_subnet=transform_binary_string(subnet)
                    net[router].cmd(f'ip route add {decimal_subnet}/{mask_size} via {best_route}')
        CLI(net)
        net.stop()

        

        
            







if __name__ == '__main__':
    main()